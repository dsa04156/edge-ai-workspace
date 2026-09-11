#!/usr/bin/env python3
"""Transactional worker/edge host address migration; preview unless --apply.

Requires Python 3.9+, PyYAML, and tomli on Python <3.11. Run on the exact target
host with the generated .host.json. Control-plane endpoint migration is a
separate operation; this tool refuses that role.
"""
import argparse
import base64
import fcntl
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import yaml

try:
    import tomllib
except ImportError:
    import tomli as tomllib

ROOT = Path('/var/backups/edgeai-network')
EDGE = Path('/etc/kubeedge/config/edgecore.yaml')
KUBE = Path('/etc/kubernetes/kubelet.conf')
DROP = Path('/etc/systemd/system/kubelet.service.d/30-edgeai-wireguard.conf')


def run(args):
    p = subprocess.run(args, text=True, capture_output=True, check=False, timeout=30)
    if p.returncode:
        raise RuntimeError('command failed: ' + ' '.join(args[:2]))
    return p.stdout.strip()


def atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.edgeai-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def changes(spec, read=lambda p: p.read_text()):
    from ipaddress import IPv4Address
    if spec['role'] not in {'edge', 'worker'}:
        raise ValueError('control plane requires the separate endpoint/certificate procedure')
    for k in ['vpn_ip', 'cloud_ip']:
        IPv4Address(spec[k])
    iface = spec['interface']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', iface):
        raise ValueError('invalid interface')
    if not 1280 <= spec['mtu'] <= 1420:
        raise ValueError('invalid MTU')
    result = {}
    if spec['role'] == 'edge':
        cfg = yaml.safe_load(read(EDGE))
        if cfg.get('apiVersion') != 'edgecore.config.kubeedge.io/v1alpha2':
            raise ValueError('only verified EdgeCore v1alpha2 shape is supported')
        mods = cfg['modules']
        if mods['edged']['hostnameOverride'] != spec['node']:
            raise ValueError('EdgeCore node identity mismatch')
        mods['edged']['customInterfaceName'] = iface
        mods['edgeHub']['httpServer'] = 'https://' + spec['cloud_ip'] + ':10002'
        mods['edgeHub']['websocket']['server'] = spec['cloud_ip'] + ':10000'
        mods['edgeStream']['server'] = spec['cloud_ip'] + ':10004'
        mods['edgeStream']['enable'] = True
        # Preserve runtime, DNS and physical-device configuration.
        result[EDGE] = yaml.safe_dump(cfg, sort_keys=False)
    else:
        cfg = yaml.safe_load(read(KUBE))
        context = next(c['context'] for c in cfg['contexts'] if c['name'] == cfg['current-context'])
        cluster = next(c['cluster'] for c in cfg['clusters'] if c['name'] == context['cluster'])
        cluster['server'] = 'https://' + spec['cloud_ip'] + ':6443'
        result[KUBE] = yaml.safe_dump(cfg, sort_keys=False)
        # A separate node-IP flag appended to the existing EXTRA_ARGS preserves
        # pre-existing flags, rather than overwriting its Environment value.
        try:
            unit = read(Path('/etc/systemd/system/kubelet.service.d/10-kubeadm.conf'))
        except FileNotFoundError:
            unit = read(Path('/usr/lib/systemd/system/kubelet.service.d/10-kubeadm.conf'))
        if '$KUBELET_EXTRA_ARGS' not in unit or '$EDGEAI_NODE_IP_ARGS' in unit:
            raise ValueError('unsupported kubelet systemd unit; inspect before migrating')
        exec_line = next((l for l in unit.splitlines() if l.startswith('ExecStart=') and l != 'ExecStart='), None)
        if not exec_line or '\\' in exec_line:
            raise ValueError('unsupported kubelet ExecStart')
        result[DROP] = '[Service]\nEnvironment="EDGEAI_NODE_IP_ARGS=--node-ip=' + spec['vpn_ip'] + '"\nExecStart=\n' + exec_line + ' $EDGEAI_NODE_IP_ARGS\n'
    service = 'edgecore' if spec['role'] == 'edge' else 'kubelet'
    ordering = Path('/etc/systemd/system') / (service + '.service.d/35-edgeai-vpn-order.conf')
    result[ordering] = '[Unit]\nRequires=wg-quick@' + iface + '.service\nAfter=wg-quick@' + iface + '.service\n'
    namespace = spec['registry_namespace']
    if not re.fullmatch(r'[0-9.]+:5000', namespace):
        raise ValueError('expected exact local registry namespace')
    IPv4Address(namespace.split(':')[0])
    endpoint = 'http://' + spec['cloud_ip'] + ':5000'
    if spec['registry_endpoint'] != endpoint:
        raise ValueError('registry endpoint must be the VPN hub')
    reg = Path('/etc/containerd/certs.d') / namespace / 'hosts.toml'
    try:
        existing = read(reg)
    except FileNotFoundError:
        existing = 'server = "' + endpoint + '"\n'
    parsed = tomllib.loads(existing)
    hosts = parsed.get('host', {})
    if endpoint in hosts:
        if not {'pull', 'resolve'} <= set(hosts[endpoint].get('capabilities', [])):
            raise ValueError('existing VPN registry entry lacks pull/resolve capabilities')
    else:
        existing = existing.rstrip() + '\n\n[host."' + endpoint + '"]\n  capabilities = ["pull", "resolve"]\n'
    # Hosts are attempted in file order; the VPN mirror must precede LAN.
    blocks = re.split(r'(?m)(?=^\[host\.)', existing)
    vpn_blocks = [b for b in blocks if b.startswith('[host.\"' + endpoint + '\"') ]
    if not vpn_blocks:
        raise ValueError('VPN mirror table not found')
    before = tomllib.loads(existing)
    root = [b for b in blocks if not b.startswith('[host.')]
    others = [b for b in blocks if b.startswith('[host.') and b not in vpn_blocks]
    existing = ''.join(b.rstrip() + '\n\n' for b in root + vpn_blocks + others)
    if tomllib.loads(existing) != before:
        raise ValueError('mirror reorder changed configuration values')
    result[reg] = existing
    wg = Path('/etc/wireguard') / (iface + '.conf')
    original = read(wg)
    if re.search(r'(?mi)^\s*SaveConfig\s*=\s*true', original):
        raise ValueError('SaveConfig=true must be resolved before migration')
    blocks = re.split(r'(?m)(?=^\[(?:Interface|Peer)\]\s*$)', original)
    found = 0
    for i, b in enumerate(blocks):
        if b.startswith('[Interface]'):
            found += 1
            b = re.sub(r'(?m)^\s*MTU\s*=.*\n?', '', b)
            blocks[i] = b.replace('[Interface]', '[Interface]\nMTU = ' + str(spec['mtu']), 1)
    if found != 1:
        raise ValueError('invalid WireGuard interface config')
    result[wg] = ''.join(blocks)
    return result


def preflight(spec):
    if socket.gethostname().split('.')[0].lower() != spec['node']:
        raise ValueError('run on the exact named node')
    addrs = json.loads(run(['ip', '-j', '-4', 'address', 'show', 'dev', spec['interface']]))
    if not any(a['local'] == spec['vpn_ip'] for n in addrs for a in n['addr_info']):
        raise ValueError('expected VPN IP not assigned')
    route = json.loads(run(['ip', '-j', '-4', 'route', 'get', spec['cloud_ip']]))
    if not route or route[0].get('dev') != spec['interface']:
        raise ValueError('hub traffic must use the WireGuard interface')
    peers = run(['wg', 'show', spec['interface'], 'latest-handshakes']).splitlines()
    if not any(0 < time.time() - int(p.split()[-1]) < 180 for p in peers):
        raise ValueError('no recent WireGuard handshake')
    run(['systemctl', 'is-active', 'containerd'])
    for port in ([10000, 10002, 10004, 5000] if spec['role'] == 'edge' else [6443, 5000]):
        with socket.create_connection((spec['cloud_ip'], port), timeout=4):
            pass
    if spec['role'] == 'edge':
        hub = yaml.safe_load(EDGE.read_text())['modules']['edgeHub']
        ca = hub.get('tlsCaFile', '/etc/kubeedge/ca/rootCA.crt')
        context = ssl.create_default_context(cafile=ca)
        port = 10002
    else:
        cfg = yaml.safe_load(KUBE.read_text())
        selected = next(c['context'] for c in cfg['contexts'] if c['name'] == cfg['current-context'])
        cluster = next(c['cluster'] for c in cfg['clusters'] if c['name'] == selected['cluster'])
        if cluster.get('certificate-authority-data'):
            context = ssl.create_default_context(cadata=base64.b64decode(cluster['certificate-authority-data']).decode())
        else:
            context = ssl.create_default_context(cafile=cluster['certificate-authority'])
        port = 6443
    with socket.create_connection((spec['cloud_ip'], port), timeout=4) as raw, context.wrap_socket(raw, server_hostname=spec['cloud_ip']):
        pass
    # Registry mirror files are live-reloaded only when certs.d is enabled.
    config = tomllib.loads(run(['containerd', 'config', 'dump']))
    def contains_certsd(value):
        if isinstance(value, dict):
            return value.get('config_path') == '/etc/containerd/certs.d' or any(contains_certsd(v) for v in value.values())
        return False
    if not contains_certsd(config):
        raise ValueError('containerd certs.d is not enabled; configure it separately before migration')
    return addrs[0]['mtu']


def restore(state_path):
    state = json.loads(state_path.read_text())
    if state['status'] in {'committed', 'rolled-back'}:
        return
    for entry in state['files']:
        path = Path(entry['path'])
        if entry['existed']:
            atomic(path, (state_path.parent / entry['backup']).read_bytes(), entry['mode'])
        else:
            path.unlink(missing_ok=True)
    run(['ip', 'link', 'set', 'dev', state['spec']['interface'], 'mtu', str(state['old_mtu'])])
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'restart', state['service']])
    state['status'] = 'rolled-back'
    atomic(state_path, json.dumps(state).encode())


def apply(spec, modified):
    old_mtu = preflight(spec)
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in ROOT.glob('*/state.json'):
        if json.loads(p.read_text()).get('status') == 'pending':
            raise ValueError('an uncommitted migration exists; verify/commit or rollback first')
    directory = ROOT / str(time.time_ns())
    directory.mkdir(mode=0o700)
    state_path = directory / 'state.json'
    service = 'edgecore' if spec['role'] == 'edge' else 'kubelet'
    state = {'spec': spec, 'status': 'pending', 'service': service, 'old_mtu': old_mtu, 'files': [],
             'timer': 'edgeai-network-rollback-' + directory.name}
    for i, path in enumerate(modified):
        if path.is_symlink():
            raise ValueError('symlink config not supported: ' + str(path))
        entry = {'path': str(path), 'existed': path.exists(), 'mode': path.stat().st_mode & 0o777 if path.exists() else 0o600, 'backup': str(i)}
        if entry['existed']:
            atomic(directory / str(i), path.read_bytes())
        state['files'].append(entry)
    atomic(state_path, json.dumps(state).encode())
    # Copy the rollback program into the root-owned backup, so later repository
    # edits cannot alter the scheduled recovery action.
    recovery = directory / 'host_network.py'
    atomic(recovery, Path(__file__).read_bytes(), 0o700)
    try:
        run(['systemd-run', '--unit', state['timer'], '--on-active=300s', sys.executable,
             str(recovery), 'rollback', '--state', str(state_path)])
        for path, text in modified.items():
            atomic(path, text.encode(), path.stat().st_mode & 0o777 if path.exists() else 0o600)
        run(['ip', 'link', 'set', 'dev', spec['interface'], 'mtu', str(spec['mtu'])])
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'restart', service])
        run(['systemctl', 'is-active', service])
    except BaseException:
        restore(state_path)
        raise
    return state_path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['preview', 'migrate', 'rollback', 'commit'])
    p.add_argument('--spec', type=Path)
    p.add_argument('--state', type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--verified-end-to-end', action='store_true')
    a = p.parse_args()
    lock_scope = ExitStack()
    try:
        if os.geteuid() == 0 and (a.apply or a.action in {'commit', 'rollback'}):
            lock = lock_scope.enter_context(open('/run/edgeai-network.lock', 'a'))  # noqa: SIM115 -- ExitStack closes in finally
            fcntl.flock(lock, fcntl.LOCK_EX)
        if a.action in {'rollback', 'commit'}:
            if os.geteuid() != 0 or not a.state or ROOT not in a.state.resolve().parents:
                raise ValueError('root and a state file under /var/backups/edgeai-network required')
            if a.action == 'rollback':
                restore(a.state)
            else:
                if not a.verified_end_to_end:
                    raise ValueError('commit requires --verified-end-to-end after cluster, DNS, workload and telemetry checks')
                state = json.loads(a.state.read_text())
                if state['status'] != 'pending':
                    raise ValueError('state is not pending')
                preflight(state['spec'])
                run(['systemctl', 'is-active', state['service']])
                run(['systemctl', 'stop', state['timer'] + '.timer'])
                state['status'] = 'committed'
                atomic(a.state, json.dumps(state).encode())
            print(a.action, 'finished')
            return 0
        if not a.spec:
            raise ValueError('--spec required')
        spec = json.loads(a.spec.read_text())
        modified = changes(spec)
        # Do not print diffs: kubeconfig and WireGuard files contain secrets.
        print(json.dumps({'node': spec['node'], 'changed_files': [str(p) for p, v in modified.items() if not p.exists() or p.read_text() != v], 'apply': a.apply}))
        if a.action == 'migrate' and a.apply:
            if os.geteuid() != 0:
                raise ValueError('root required')
            if all(p.exists() and p.read_text() == v for p, v in modified.items()):
                print('configuration unchanged; run end-to-end verification')
                return 0
            print('pending verification; automatic rollback in 300 seconds; state:', apply(spec, modified))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, yaml.YAMLError) as e:
        # Parser diagnostics may contain secret-bearing configuration lines.
        print('ERROR:', type(e).__name__, '; migration stopped; inspect locally without publishing config contents', file=sys.stderr)
        return 2
    finally:
        lock_scope.close()


if __name__ == '__main__':
    sys.exit(main())
