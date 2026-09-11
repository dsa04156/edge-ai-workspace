#!/usr/bin/env python3
"""Prepare the exact PoC's temporary mixed-LAN/VPN transit, then finalize it.

Python 3.7 compatible for the LAN-only Tinker. Does not install WireGuard,
change node identities, restart workloads, or replace private keys.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

NODES = {'etri-ser0001-cg0msb': ('56', '1'), 'etri-ser0002-cgnmsb': ('5', '5'),
         'etri-dev0001-jetorn': ('3', '3'), 'etri-dev0002-raspi5': ('4', '4'),
         'etri-dev0003-raspi5': ('6', '6'), 'etri-dev0004-tedger': ('7', None),
         'etri-dev0005-jetagx': ('8', '8')}
CONF = Path('/etc/wireguard/wg0.conf')
INSTALLED = Path('/usr/local/lib/edgeai-network/prepare_vpn_routes.py')


def run(args, stdin=None):
    p = subprocess.run(args, input=stdin, text=True, capture_output=True, timeout=30, check=False)
    if p.returncode:
        raise RuntimeError('command failed: ' + args[0] + ' ' + args[1])
    return p.stdout.strip()


def atomic(path, text, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.edgeai-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def edit_config(original, hub, final):
    blocks = re.split(r'(?m)(?=^\[(?:Interface|Peer)\]\s*$)', original)
    if sum(b.startswith('[Interface]') for b in blocks) != 1:
        raise ValueError('invalid interface section')
    for i, b in enumerate(blocks):
        if b.startswith('[Interface]'):
            tables = re.findall(r'(?m)^\s*Table\s*=\s*(\S+)', b)
            if any(t not in ['auto', 'off'] for t in tables):
                raise ValueError('custom policy routing requires separate review')
            if re.search(r'(?mi)^\s*SaveConfig\s*=\s*true', b):
                raise ValueError('SaveConfig=true not supported')
            b = re.sub(r'(?m)^\s*(?:Table|MTU)\s*=.*\n?', '', b)
            b = b.replace('[Interface]', '[Interface]\nMTU = 1380' + ('' if final else '\nTable = off'), 1)
        elif b.startswith('[Peer]'):
            matches = re.findall(r'(?m)^\s*AllowedIPs\s*=\s*(.*?)\s*$', b)
            if len(matches) != 1:
                raise ValueError('ambiguous peer AllowedIPs')
            existing = [s.strip() for s in matches[0].split(',')]
            if hub:
                mapping = {('10.77.0.' + v + '/32'): ('192.168.0.' + lan + '/32') for lan, v in NODES.values() if v and v != '1'}
                key = next((k for k in mapping if k in existing), None)
                if not key:
                    continue  # Preserve reserved/unrelated peer, including .47.
                allowed = [s for s in existing if s != mapping[key]]
                if not final:
                    allowed.append(mapping[key])
            else:
                if '10.77.0.0/24' not in existing:
                    raise ValueError('unexpected spoke peer; no mutation')
                known = {'192.168.0.' + lan + '/32' for lan, _ in NODES.values()}
                allowed = [s for s in existing if s not in known]
                allowed += ['192.168.0.7/32'] if final else sorted(known)
            b = re.sub(r'(?m)^\s*AllowedIPs\s*=.*$', 'AllowedIPs = ' + ', '.join(dict.fromkeys(allowed)), b)
        blocks[i] = b
    return ''.join(blocks)


def route(prefix, dev=None, via=None):
    current = json.loads(run(['ip', '-j', '-4', 'route', 'show', 'exact', prefix]))
    if current:
        if dev and all(r.get('dev') != dev for r in current):
            raise ValueError('conflicting route: ' + prefix)
        if via and all(r.get('gateway') != via for r in current):
            raise ValueError('conflicting return route: ' + prefix)
        return
    args = ['ip', '-4', 'route', 'add', prefix]
    args += ['via', via] if via else ['dev', dev]
    run(args)


def runtime(name):
    _lan, vpn = NODES[name]
    if vpn is None:
        route('10.77.0.0/24', via='192.168.0.56')
        return
    route('10.77.0.0/24', dev='wg0')
    if vpn != '1':
        route('192.168.0.7/32', dev='wg0')
    run(['sysctl', '-w', 'net.ipv4.conf.all.rp_filter=2'])
    if vpn == '1':
        run(['sysctl', '-w', 'net.ipv4.ip_forward=1'])
        chain = 'EDGEAI_WG_TRANSIT'
        subprocess.run(['iptables', '-w', '5', '-N', chain], capture_output=True, check=False)
        rules = [('-i', 'wg0', '-s', '10.77.0.0/24', '-d', '10.77.0.0/24', '-j', 'ACCEPT'),
                 ('-i', 'wg0', '-s', '10.77.0.0/24', '-d', '192.168.0.7/32', '-j', 'ACCEPT'),
                 ('-s', '192.168.0.7/32', '-o', 'wg0', '-d', '10.77.0.0/24', '-j', 'ACCEPT')]
        for rule in rules:
            if subprocess.run(['iptables', '-w', '5', '-C', chain] + list(rule), capture_output=True, check=False).returncode:
                run(['iptables', '-w', '5', '-A', chain] + list(rule))
        final = Path('/etc/edgeai-network/routing-phase').read_text().strip() == 'final'
        for old_lan, old_vpn in NODES.values():
            if not old_vpn or old_vpn == '1':
                continue
            rule = ['-i', 'wg0', '-s', '192.168.0.' + old_lan + '/32', '-o', 'wg0', '-d', '10.77.0.0/24', '-j', 'ACCEPT']
            present = subprocess.run(['iptables', '-w', '5', '-C', chain] + rule, capture_output=True, check=False).returncode == 0
            if present and final:
                run(['iptables', '-w', '5', '-D', chain] + rule)
            elif not present and not final:
                run(['iptables', '-w', '5', '-A', chain] + rule)
        hook = ['-m', 'comment', '--comment', 'edgeai-wireguard-transit', '-j', chain]
        if subprocess.run(['iptables', '-w', '5', '-C', 'FORWARD'] + hook, capture_output=True, check=False).returncode:
            run(['iptables', '-w', '5', '-I', 'FORWARD', '1'] + hook)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--finalize', action='store_true')
    p.add_argument('--runtime', action='store_true')
    a = p.parse_args()
    name = socket.gethostname().split('.')[0].lower()
    if name not in NODES or os.geteuid() != 0:
        raise ValueError('root on an inventoried node required')
    if a.runtime:
        runtime(name)
        return
    _lan, vpn = NODES[name]
    original = CONF.read_text() if vpn else None
    changed = edit_config(original, vpn == '1', a.finalize) if vpn else None
    print(json.dumps({'node': name, 'phase': 'final' if a.finalize else 'mixed-transit', 'apply': a.apply}))
    if not a.apply:
        return
    backup = Path('/var/backups/edgeai-network') / ('routing-' + str(time.time_ns()))
    backup.mkdir(parents=True, mode=0o700)
    writeback = {CONF: changed} if vpn else {}
    writeback[Path('/etc/edgeai-network/routing-phase')] = 'final\n' if a.finalize else 'mixed\n'
    if vpn:
        drop = Path('/etc/systemd/system/wg-quick@wg0.service.d/30-edgeai-routes.conf')
        writeback[drop] = '[Service]\nExecStartPost=/usr/bin/python3 ' + str(INSTALLED) + ' --runtime\n'
        writeback[Path('/etc/sysctl.d/99-edgeai-wireguard-routing.conf')] = 'net.ipv4.conf.all.rp_filter = 2\n' + ('net.ipv4.ip_forward = 1\n' if vpn == '1' else '')
    else:
        writeback[Path('/etc/systemd/system/edgeai-vpn-return-route.service')] = ('[Unit]\nDescription=Edge AI VPN return route\nAfter=network-online.target\nWants=network-online.target\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=/usr/bin/python3 ' + str(INSTALLED) + ' --runtime\n[Install]\nWantedBy=multi-user.target\n')
    writeback[INSTALLED] = Path(__file__).read_text()
    state = {}
    for i, (path, text) in enumerate(writeback.items()):
        if path.is_symlink():
            raise ValueError('symlink in managed files')
        state[str(path)] = {'exists': path.exists(), 'backup': str(i)}
        if path.exists():
            atomic(backup / str(i), path.read_text())
    atomic(backup / 'files.json', json.dumps(state))
    live = run(['wg', 'showconf', 'wg0']) if vpn else None
    # All file changes and live peer sync are backed up before route changes.
    try:
        for path, text in writeback.items():
            atomic(path, text, 0o700 if path == INSTALLED else 0o600)
        if vpn:
            stripped = run(['wg-quick', 'strip', str(CONF)])
            run(['wg', 'syncconf', 'wg0', '/dev/stdin'], stripped)
            run(['ip', 'link', 'set', 'dev', 'wg0', 'mtu', '1380'])
        runtime(name)
        run(['systemctl', 'daemon-reload'])
        if not vpn:
            run(['systemctl', 'enable', '--now', 'edgeai-vpn-return-route.service'])
    except BaseException:
        for path, saved in state.items():
            if saved['exists']:
                atomic(Path(path), (backup / saved['backup']).read_text())
            elif Path(path).exists():
                Path(path).unlink()
        if vpn:
            run(['wg', 'syncconf', 'wg0', '/dev/stdin'], live)
        run(['systemctl', 'daemon-reload'])
        raise
    print('routing prepared; backup:', backup)


if __name__ == '__main__':
    main()
