#!/usr/bin/env python3
"""Review/add/update one existing WireGuard interface's peer without restarting it.

Default is read-only. Private keys never appear in output. Route/interface
changes belong to the host migration procedure, not to syncconf.
"""
import argparse
import base64
import fcntl
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def key(value):
    try:
        if len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('public key must be a base64-encoded 32-byte key') from None
    return value


def networks(value):
    result = [ipaddress.IPv4Network(v.strip(), strict=True) for v in value.split(',')]
    if not result or any(n.prefixlen == 0 for n in result):
        raise ValueError('empty/default routes are not supported')
    return result


def sections(text):
    # Keep untouched blocks byte-for-byte, including comments and key material.
    return re.split(r'(?m)(?=^\[(?:Interface|Peer)\]\s*$)', text)


def values(block):
    result = {}
    for line in block.splitlines():
        line = line.split('#', 1)[0].strip()
        if '=' in line:
            name, value = line.split('=', 1)
            result.setdefault(name.strip(), []).append(value.strip())
    return result


def peer_keys(text):
    return {v for b in sections(text) if b.startswith('[Peer]') for v in values(b).get('PublicKey', [])}


def reconcile(original, public_key, allowed_ips, endpoint=None, keepalive=None):
    key(public_key)
    requested = networks(allowed_ips)
    if endpoint is not None and not re.fullmatch(r'[A-Za-z0-9.-]+:[0-9]{1,5}', endpoint):
        raise ValueError('endpoint must be host:port')
    if endpoint and not 1 <= int(endpoint.rsplit(':', 1)[1]) <= 65535:
        raise ValueError('invalid endpoint port')
    if keepalive is not None and not 0 <= keepalive <= 65535:
        raise ValueError('invalid keepalive')
    blocks = sections(original)
    if sum(b.startswith('[Interface]') for b in blocks) != 1:
        raise ValueError('expected exactly one Interface section')
    matches = []
    for i, b in enumerate(blocks):
        opts = values(b)
        if b.startswith('[Interface]'):
            if any(v.lower() == 'true' for v in opts.get('SaveConfig', [])):
                raise ValueError('SaveConfig=true is incompatible with persistent peer editing')
            for a in opts.get('Address', []):
                for item in a.split(','):
                    host = ipaddress.ip_interface(item.strip()).ip
                    if any(n.prefixlen == 32 and host in n for n in requested):
                        raise ValueError('peer AllowedIPs contains the local interface address')
        if not b.startswith('[Peer]'):
            continue
        pubs = opts.get('PublicKey', [])
        if len(pubs) != 1:
            raise ValueError('peer must have exactly one public key')
        existing = [n for v in opts.get('AllowedIPs', []) for n in networks(v)]
        if pubs[0] == public_key:
            matches.append(i)
        elif any(a.overlaps(b) for a in requested for b in existing):
            raise ValueError('AllowedIPs overlaps another peer')
    if len(matches) > 1:
        raise ValueError('duplicate public key sections')
    desired = {'PublicKey': public_key, 'AllowedIPs': ', '.join(map(str, requested))}
    if endpoint is not None:
        desired['Endpoint'] = endpoint
    if keepalive is not None:
        desired['PersistentKeepalive'] = str(keepalive)
    if not matches:
        return original.rstrip() + '\n\n[Peer]\n' + ''.join(f'{k} = {v}\n' for k, v in desired.items())
    pos = matches[0]
    opts = values(blocks[pos])
    if all(opts.get(k) == [v] for k, v in desired.items()):
        return original
    lines, seen = [], set()
    for line in blocks[pos].splitlines(keepends=True):
        name = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else ''
        if name in desired:
            if name not in seen:
                lines.append(f'{name} = {desired[name]}\n')
                seen.add(name)
        else:
            lines.append(line)
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    lines += [f'{k} = {v}\n' for k, v in desired.items() if k not in seen]
    blocks[pos] = ''.join(lines)
    return ''.join(blocks)


def run(argv, input=None):
    proc = subprocess.run(argv, input=input, text=True, capture_output=True, check=False, timeout=20)
    if proc.returncode:
        # wg parse diagnostics can include the offending key; do not forward stderr.
        raise RuntimeError('command failed: ' + argv[0] + ' ' + argv[1])
    return proc.stdout


def atomic(path, content):
    fd, name = tempfile.mkstemp(prefix='.wg-peer-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply(path, iface, original, updated):
    if os.geteuid() != 0:
        raise ValueError('--apply requires root')
    if updated == original:
        return None
    live = run(['wg', 'showconf', iface])
    if not peer_keys(live) <= peer_keys(original):
        raise ValueError('live interface has unpersisted peers; reconcile inventory before syncconf')
    configured_key = values(next(b for b in sections(original) if b.startswith('[Interface]'))).get('PrivateKey', [])
    if len(configured_key) != 1 or run(['wg', 'pubkey'], input=configured_key[0] + '\n').strip() != run(['wg', 'show', iface, 'public-key']).strip():
        raise ValueError('file and live interface identity differ')
    # syncconf does not install routes. Require all allowed ranges to already be
    # covered by an explicit wg route before changing persistent or live state.
    routes = json.loads(run(['ip', '-j', '-4', 'route', 'show', 'dev', iface]))
    covered = [ipaddress.ip_network(r['dst']) for r in routes if r.get('dst') not in (None, 'default')]
    for block in sections(updated):
        if block.startswith('[Peer]'):
            for text in values(block).get('AllowedIPs', []):
                if any(not any(n.subnet_of(route) for route in covered) for n in networks(text)):
                    raise ValueError('AllowedIPs lacks an existing interface route; prepare host routing first')
    with tempfile.TemporaryDirectory(prefix='wg-peer-') as directory:
        candidate = Path(directory) / (iface + '.conf')
        candidate.write_text(updated)
        candidate.chmod(0o600)
        stripped = run(['wg-quick', 'strip', str(candidate)])
        backup = path.with_name(path.name + '.backup-' + str(time.time_ns()))
        shutil.copy2(path, backup)
        backup.chmod(0o600)
        try:
            atomic(path, updated)
            run(['wg', 'syncconf', iface, '/dev/stdin'], input=stripped)
            if peer_keys(run(['wg', 'showconf', iface])) != peer_keys(updated):
                raise RuntimeError('live peer verification failed')
        except BaseException:
            atomic(path, original)
            run(['wg', 'syncconf', iface, '/dev/stdin'], input=live)
            raise
        return backup


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--interface', default='wg0')
    p.add_argument('--config', type=Path, default=Path('/etc/wireguard/wg0.conf'))
    p.add_argument('--public-key', required=True)
    p.add_argument('--allowed-ips', required=True)
    p.add_argument('--endpoint')
    p.add_argument('--keepalive', type=int)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', a.interface):
            raise ValueError('invalid interface name')
        if a.config.is_symlink() or not a.config.is_file():
            raise ValueError('existing regular config file required')
        # Lock a stable sidecar, not an inode replaced by atomic(). Read-only
        # preview never creates it and rechecks bytes under lock during apply.
        original = a.config.read_text()
        updated = reconcile(original, a.public_key, a.allowed_ips, a.endpoint, a.keepalive)
        print(json.dumps({'interface': a.interface, 'public_key': a.public_key,
                          'allowed_ips': a.allowed_ips, 'changed': original != updated,
                          'mode': 'apply' if a.apply else 'preview'}))
        if a.apply:
            if os.geteuid() != 0:
                raise ValueError('--apply requires root')
            with a.config.with_suffix('.peer.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if a.config.read_text() != original:
                    raise ValueError('config changed concurrently; rerun preview')
                backup = apply(a.config, a.interface, original, updated)
                print('backup:', backup or 'unchanged')
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as e:
        print('ERROR:', str(e), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
