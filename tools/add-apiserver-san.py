#!/usr/bin/env python3
"""Add one API-server certificate SAN on this control plane; requires host root.

Does not change the public join endpoint or router forwarding. Existing SANs,
CA, kubeconfigs and API-server advertise address are preserved.
"""
import argparse
import copy
import datetime
import json
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import time

import yaml

PKI = Path('/etc/kubernetes/pki')
ADMIN = '/etc/kubernetes/admin.conf'
LOCAL = '192.168.0.56'
EXTRA = '10.254.192.217'
CRI = ['crictl', '--runtime-endpoint=unix:///run/containerd/containerd.sock']


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def kubectl(*args):
    return run(['kubectl', '--kubeconfig', ADMIN, '--context=kubernetes-admin@kubernetes', '--request-timeout=10s', *args])


def sans(path):
    cert = ssl._ssl._test_decode_cert(str(path))
    return [value for kind, value in cert.get('subjectAltName', [])
            if kind in ('DNS', 'IP Address')]


def configuration(original, existing, directory):
    updated = copy.deepcopy(original)
    updated.setdefault('apiServer', {})['certSANs'] = sorted(set(
        existing + updated.get('apiServer', {}).get('certSANs', []) + [EXTRA]))
    staged = copy.deepcopy(updated)
    staged['certificatesDir'] = str(directory)
    init = {'apiVersion': updated['apiVersion'], 'kind': 'InitConfiguration',
            'localAPIEndpoint': {'advertiseAddress': LOCAL, 'bindPort': 6443}}
    return updated, [init, staged]


def replace_file(source, target, mode):
    # Temp files stay outside the watched manifest directory.
    fd, name = tempfile.mkstemp(prefix='.san-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(source.read_bytes())
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, mode)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def restart_apiserver():
    ids = run(CRI + ['ps', '--name', 'kube-apiserver', '-q']).splitlines()
    if len(ids) != 1:
        raise RuntimeError('Expected exactly one running local kube-apiserver')
    run(CRI + ['stop', '--timeout', '20', ids[0]])


def healthy(expected_pem, hostname, timeout=120):
    deadline = time.monotonic() + timeout
    ctx = ssl.create_default_context(cafile=str(PKI / 'ca.crt'))
    expected = ssl.PEM_cert_to_DER_cert(expected_pem)
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((LOCAL, 6443), timeout=3) as raw:
                with ctx.wrap_socket(raw, server_hostname=hostname) as conn:
                    if conn.getpeercert(binary_form=True) != expected:
                        raise RuntimeError('API server still serves another certificate')
            if kubectl('get', '--raw=/readyz') == 'ok':
                return
        except (OSError, RuntimeError, subprocess.CalledProcessError):
            time.sleep(2)
    raise RuntimeError('API certificate/readiness verification timed out')


def main():
    global EXTRA
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='back up, replace SAN certificate and restart API server')
    parser.add_argument('--san', default=EXTRA, help='additional IPv4 SAN; preserves all current SANs')
    args = parser.parse_args()
    requested = ipaddress.ip_address(args.san)
    if requested.version != 4 or requested.is_unspecified or requested.is_multicast or requested.is_loopback:
        parser.error('--san must be a unicast, non-loopback IPv4 address')
    EXTRA = str(requested)
    if not args.apply:
        print('Existing SANs:', ', '.join(sans(PKI / 'apiserver.crt')))
        print('Planned addition:', EXTRA)
        print('Apply requires: sudo python3 tools/add-apiserver-san.py --san', EXTRA, '--apply')
        return
    if os.geteuid() != 0:
        raise SystemExit('Host root is required; no changes made.')
    os.umask(0o077)
    for binary in ('kubectl', 'kubeadm', 'openssl', 'crictl'):
        if not shutil.which(binary):
            raise SystemExit('Missing executable: ' + binary)
    original_cm = json.loads(kubectl('get', 'cm', 'kubeadm-config', '-n', 'kube-system', '-o', 'json'))
    config = yaml.safe_load(original_cm['data']['ClusterConfiguration'])
    if config.get('certificatesDir') != str(PKI):
        raise SystemExit('Unexpected certificate directory; no changes made.')
    if kubectl('get', '--raw=/readyz') != 'ok':
        raise SystemExit('API server is not ready; no changes made.')
    if len(run(CRI + ['ps', '--name', 'kube-apiserver', '-q']).splitlines()) != 1:
        raise SystemExit('Unexpected local API-server container count; no changes made.')
    existing = sans(PKI / 'apiserver.crt')
    if EXTRA in existing:
        healthy((PKI / 'apiserver.crt').read_text(), EXTRA, timeout=15)
        print('Requested SAN is already served and API server is ready.')
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path('/var/backups/kubernetes') / ('apiserver-san-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    for name in ('apiserver.crt', 'apiserver.key'):
        shutil.copy2(PKI / name, backup / name)
    (backup / 'kubeadm-config.json').write_text(json.dumps(original_cm))
    updated = None
    changed = False
    try:
        with tempfile.TemporaryDirectory(prefix='apiserver-san-', dir='/var/tmp') as tmp:
            stage = Path(tmp)
            for name in ('ca.crt', 'ca.key'):
                shutil.copy2(PKI / name, stage / name)
            updated, docs = configuration(config, existing, stage)
            cfg = stage / 'kubeadm.yaml'
            cfg.write_text(yaml.safe_dump_all(docs))
            run(['kubeadm', 'init', 'phase', 'certs', 'apiserver', '--config', str(cfg)])
            if not set(existing + [EXTRA]).issubset(sans(stage / 'apiserver.crt')):
                raise RuntimeError('Generated certificate lost a required SAN')
            run(['openssl', 'verify', '-CAfile', str(PKI / 'ca.crt'), str(stage / 'apiserver.crt')])
            cert_key = run(['openssl', 'x509', '-in', str(stage / 'apiserver.crt'), '-pubkey', '-noout'])
            private_key = run(['openssl', 'pkey', '-in', str(stage / 'apiserver.key'), '-pubout'])
            if cert_key != private_key:
                raise RuntimeError('Generated key does not match the certificate')
            changed = True
            replace_file(stage / 'apiserver.key', PKI / 'apiserver.key', 0o600)
            replace_file(stage / 'apiserver.crt', PKI / 'apiserver.crt', 0o644)
            # TLS certificate loading may be dynamic; avoid a restart if it is already served.
            try:
                healthy((PKI / 'apiserver.crt').read_text(), EXTRA, timeout=6)
            except RuntimeError:
                restart_apiserver()
                healthy((PKI / 'apiserver.crt').read_text(), EXTRA)
        patch = {'data': {'ClusterConfiguration': yaml.safe_dump(updated)}}
        kubectl('patch', 'cm', 'kubeadm-config', '-n', 'kube-system', '--type=merge', '-p', json.dumps(patch))
    except Exception:
        if changed:
            print('Apply failed; restoring previous certificate. Backup:', backup)
            replace_file(backup / 'apiserver.key', PKI / 'apiserver.key', 0o600)
            replace_file(backup / 'apiserver.crt', PKI / 'apiserver.crt', 0o644)
            try:
                restart_apiserver()
            except (RuntimeError, subprocess.CalledProcessError):
                pass  # Kubelet may already be restarting it.
            healthy((PKI / 'apiserver.crt').read_text(), LOCAL)
            kubectl('patch', 'cm', 'kubeadm-config', '-n', 'kube-system', '--type=merge',
                    '-p', json.dumps({'data': {'ClusterConfiguration': original_cm['data']['ClusterConfiguration']}}))
        raise
    print('SAN added and verified against the serving API certificate:', EXTRA)
    print('API /readyz: ok. Backup:', backup)
    print('Port forwarding and external worker join endpoint are still pending.')


if __name__ == '__main__':
    main()
