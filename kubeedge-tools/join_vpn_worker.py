#!/usr/bin/env python3
"""Called by onboard-vpn-node.sh after VPN/kernel preflight; token stays off argv."""
import getpass
import ipaddress
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def join_config(env, token):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,61}[a-z0-9]', env['NODE_NAME']):
        raise ValueError('invalid node name')
    for field in ['NODE_VPN_IP', 'CLOUD_VPN_IP']:
        address = ipaddress.IPv4Address(env[field])
        if not address.is_private or address.is_loopback or address.is_unspecified:
            raise ValueError('expected private VPN host address')
    version = env['KUBERNETES_VERSION']
    if not re.fullmatch(r'v1\.31\.\d+', version):
        raise ValueError('this worker join path is verified for Kubernetes 1.31 / kubeadm v1beta4')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', env['DISCOVERY_CA_HASH']):
        raise ValueError('invalid discovery CA hash')
    if not re.fullmatch(r'[a-z0-9]{6}\.[a-z0-9]{16}', token):
        raise ValueError('invalid bootstrap token format')
    return {'apiVersion': 'kubeadm.k8s.io/v1beta4', 'kind': 'JoinConfiguration',
            'discovery': {'bootstrapToken': {'token': token,
                'apiServerEndpoint': env['CLOUD_VPN_IP'] + ':6443',
                'caCertHashes': [env['DISCOVERY_CA_HASH']]}},
            'nodeRegistration': {'name': env['NODE_NAME'],
                'criSocket': 'unix:///run/containerd/containerd.sock',
                'kubeletExtraArgs': [{'name': 'node-ip', 'value': env['NODE_VPN_IP']}]}}


def main():
    if os.geteuid() != 0 or not os.isatty(0):
        raise ValueError('root and interactive hidden token input required')
    if Path('/etc/kubernetes/kubelet.conf').exists() or Path('/etc/kubeedge/config/edgecore.yaml').exists():
        raise ValueError('existing node state; refusing rejoin')
    for binary, args in [('kubeadm', ['version', '-o', 'short']), ('kubelet', ['--version'])]:
        installed = subprocess.check_output([binary] + args, text=True).strip().split()[-1]
        if installed != os.environ['KUBERNETES_VERSION']:
            raise ValueError('installed ' + binary + ' version mismatch')
    token = getpass.getpass('Kubernetes bootstrap token: ')
    config = join_config(os.environ, token)
    del token
    subprocess.run(['hostnamectl', 'set-hostname', os.environ['NODE_NAME']], check=True, capture_output=True)
    with tempfile.TemporaryDirectory(prefix='vpn-worker-') as directory:
        path = Path(directory) / 'join.json'
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f)
        config['discovery']['bootstrapToken']['token'] = ''
        proc = subprocess.run(['kubeadm', 'join', '--config', str(path)], capture_output=True, check=False)
        # Do not echo a potentially secret-bearing bootstrap error log.
        if proc.returncode:
            raise RuntimeError('kubeadm join failed; node may have partial state, inspect before retrying')
    print('worker joined; end-to-end verification required')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as e:
        raise SystemExit(str(e))
