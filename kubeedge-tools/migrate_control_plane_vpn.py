#!/usr/bin/env python3
"""Exact single-control-plane VPN migration with an independent rollback timer."""
import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import yaml
from host_network import atomic

ROOT = Path('/var/backups/edgeai-network')
OLD = '192.168.0.56'
NEW = '10.77.0.1'
K = ['kubectl', '--kubeconfig=/etc/kubernetes/admin.conf', '--context=kubernetes-admin@kubernetes']


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    if p.returncode:
        raise RuntimeError('command failed: ' + args[0])
    return p.stdout


def changes():
    result = {}
    for name in ['/etc/default/kubelet', '/etc/systemd/system/kubelet.service.d/20-nodeip.conf']:
        path = Path(name)
        old = path.read_text()
        if '--node-ip=' + OLD not in old:
            raise ValueError('unexpected kubelet node-IP baseline')
        result[path] = old.replace('--node-ip=' + OLD, '--node-ip=' + NEW)
    path = Path('/etc/kubernetes/kubelet.conf')
    cfg = yaml.safe_load(path.read_text())
    for cluster in cfg['clusters']:
        if cluster['cluster']['server'] == 'https://' + OLD + ':6443':
            cluster['cluster']['server'] = 'https://' + NEW + ':6443'
    result[path] = yaml.safe_dump(cfg, sort_keys=False)
    path = Path('/etc/kubernetes/manifests/kube-apiserver.yaml')
    cfg = yaml.safe_load(path.read_text())
    container = next(c for c in cfg['spec']['containers'] if c['name'] == 'kube-apiserver')
    assert '--advertise-address=' + OLD in container['command']
    container['command'] = [v.replace('--advertise-address=' + OLD, '--advertise-address=' + NEW) for v in container['command']]
    for probe in ['livenessProbe', 'readinessProbe', 'startupProbe']:
        if container.get(probe, {}).get('httpGet', {}).get('host') == OLD:
            container[probe]['httpGet']['host'] = NEW
    cfg['metadata']['annotations']['kubeadm.kubernetes.io/kube-apiserver.advertise-address.endpoint'] = NEW + ':6443'
    result[path] = yaml.safe_dump(cfg, sort_keys=False)
    result[Path('/etc/systemd/system/kubelet.service.d/35-edgeai-vpn-order.conf')] = '[Unit]\nRequires=wg-quick@wg0.service\nAfter=wg-quick@wg0.service\n'
    return result


def restore(state_path):
    state = json.loads(state_path.read_text())
    if state['status'] != 'pending':
        return
    for entry in state['files']:
        path = Path(entry['path'])
        if entry['existed']:
            atomic(path, (state_path.parent / entry['backup']).read_bytes(), entry['mode'])
        else:
            path.unlink(missing_ok=True)
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'restart', 'kubelet'])
    state['status'] = 'rolled-back'
    atomic(state_path, json.dumps(state).encode())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['preview', 'apply', 'commit', 'rollback'])
    p.add_argument('--state', type=Path)
    p.add_argument('--verified-end-to-end', action='store_true')
    a = p.parse_args()
    if os.geteuid() != 0 or socket.gethostname().lower() != 'etri-ser0001-cg0msb':
        raise ValueError('exact control-plane host and root required')
    os.umask(0o077)
    with open('/run/edgeai-control-vpn.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if a.action in ['rollback', 'commit']:
            if not a.state or ROOT not in a.state.resolve().parents:
                raise ValueError('invalid state path')
            if a.action == 'rollback':
                restore(a.state)
                return
            state = json.loads(a.state.read_text())
            assert a.verified_end_to_end and state['status'] == 'pending'
            assert run(K + ['--server=https://' + NEW + ':6443', 'get', '--raw=/readyz']).strip() == 'ok'
            node = json.loads(run(K + ['get', 'node', 'etri-ser0001-cg0msb', '-o', 'json']))
            assert any(v['type'] == 'InternalIP' and v['address'] == NEW for v in node['status']['addresses'])
            run(['systemctl', 'stop', state['timer'] + '.timer'])
            state['status'] = 'committed'
            atomic(a.state, json.dumps(state).encode())
            print('control-plane host committed')
            return
        modified = changes()
        print(json.dumps({'files': [str(v) for v in modified], 'action': a.action}), flush=True)
        if a.action == 'preview':
            return
        assert run(['systemctl', 'is-active', 'wg-quick@wg0']).strip() == 'active'
        assert run(K + ['--server=https://' + NEW + ':6443', 'get', '--raw=/readyz']).strip() == 'ok'
        assert NEW in run(['ip', '-4', 'addr', 'show', 'wg0'])
        for path in ROOT.glob('control-plane-*/state.json'):
            assert json.loads(path.read_text())['status'] != 'pending'
        directory = ROOT / ('control-plane-' + str(time.time_ns()))
        directory.mkdir(parents=True, mode=0o700)
        state_path = directory / 'state.json'
        state = {'status': 'pending', 'timer': 'edgeai-control-vpn-' + directory.name, 'files': []}
        for i, path in enumerate(modified):
            assert not path.is_symlink()
            entry = {'path': str(path), 'existed': path.exists(), 'backup': str(i), 'mode': path.stat().st_mode & 0o777 if path.exists() else 0o600}
            if path.exists():
                atomic(directory / str(i), path.read_bytes())
            state['files'].append(entry)
        atomic(state_path, json.dumps(state).encode())
        for name in ['migrate_control_plane_vpn.py', 'host_network.py']:
            atomic(directory / name, (Path(__file__).parent / name).read_bytes(), 0o700)
        run(['systemd-run', '--unit', state['timer'], '--on-active=600s', sys.executable, str(directory / Path(__file__).name), 'rollback', '--state', str(state_path)])
        try:
            for path, value in modified.items():
                atomic(path, value.encode(), path.stat().st_mode & 0o777 if path.exists() else 0o600)
            run(['systemctl', 'daemon-reload'])
            run(['systemctl', 'restart', 'kubelet'])
        except BaseException:
            restore(state_path)
            raise
        print('pending verification; automatic host rollback in 600 seconds; state:', state_path)


if __name__ == '__main__':
    main()
