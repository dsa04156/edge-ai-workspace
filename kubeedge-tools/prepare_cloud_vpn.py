#!/usr/bin/env python3
"""Add the VPN CloudHub SAN using the existing CA/key and preserve live Helm drift.

Root-only, exact current cluster/release. Backups and reconstructed chart/Helm
payloads can contain secrets and remain under /var/backups, never in Git.
"""
import argparse
import base64
import copy
import datetime
import gzip
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import time
from pathlib import Path

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import serialization

CONTEXT = 'kubernetes-admin@kubernetes'
K = ['kubectl', '--kubeconfig=/etc/kubernetes/admin.conf', '--context=' + CONTEXT]
H = ['helm', '--kubeconfig=/etc/kubernetes/admin.conf', '--kube-context=' + CONTEXT]


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=240, check=False)
    if p.returncode:
        raise RuntimeError('command failed: ' + args[0] + ' (private diagnostics withheld)')
    return p.stdout


def obj(kind, name):
    return json.loads(run(K + ['get', kind, name, '-n', 'kubeedge', '-o', 'json']))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)
    path.chmod(0o600)


def renew(ca_der, ca_key_der, old_der, ip):
    ca = x509.load_der_x509_certificate(ca_der)
    key = serialization.load_der_private_key(ca_key_der, password=None)
    old = x509.load_der_x509_certificate(old_der)
    public = lambda k: k.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if public(key.public_key()) != public(ca.public_key()) or old.issuer != ca.subject:
        raise ValueError('CA identity mismatch')
    san = old.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    addresses = list(san.value)
    requested = x509.IPAddress(ipaddress.IPv4Address(ip))
    if requested in addresses:
        return old_der
    addresses.append(requested)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    builder = (x509.CertificateBuilder().subject_name(old.subject).issuer_name(old.issuer)
               .public_key(old.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(max(ca.not_valid_before, now - datetime.timedelta(minutes=5)))
               .not_valid_after(min(ca.not_valid_after, old.not_valid_after)))
    for extension in old.extensions:
        value = x509.SubjectAlternativeName(addresses) if isinstance(extension.value, x509.SubjectAlternativeName) else extension.value
        builder = builder.add_extension(value, extension.critical)
    return builder.sign(key, old.signature_hash_algorithm).public_bytes(serialization.Encoding.DER)


def served(ca_der, expected, ip, timeout=90):
    pem = x509.load_der_x509_certificate(ca_der).public_bytes(serialization.Encoding.PEM).decode()
    ctx = ssl.create_default_context(cadata=pem)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((ip, 10002), timeout=3) as raw, ctx.wrap_socket(raw, server_hostname=ip) as conn:
                if conn.getpeercert(binary_form=True) == expected:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise RuntimeError('CloudHub serving certificate validation timed out')


def capture_release(release, directory):
    releases = json.loads(run(H + ['list', '-n', 'kubeedge', '-o', 'json']))
    current = next(r for r in releases if r['name'] == release)
    packed = obj('secret', 'sh.helm.release.v1.' + release + '.v' + current['revision'])
    decoded = json.loads(gzip.decompress(base64.b64decode(base64.b64decode(packed['data']['release']))))
    write(directory / 'original-release.json', decoded)
    chart = directory / 'chart'
    chart.mkdir(mode=0o700)
    write(chart / 'Chart.yaml', yaml.safe_dump(decoded['chart']['metadata']))
    write(chart / 'values.yaml', yaml.safe_dump(decoded['chart']['values']))
    for entry in decoded['chart'].get('templates', []) + decoded['chart'].get('files', []):
        relative = Path(entry['name'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('invalid chart path')
        path = chart / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(base64.b64decode(entry['data']))
        path.chmod(0o600)
    if decoded['chart'].get('schema'):
        (chart / 'values.schema.json').write_bytes(base64.b64decode(decoded['chart']['schema']))
    live = {}
    for doc in yaml.safe_load_all(decoded['manifest']):
        if not doc:
            continue
        name, kind = doc['metadata']['name'], doc['kind']
        ns = doc['metadata'].get('namespace', 'kubeedge')
        p = subprocess.run(K + ['get', kind, name, '-n', ns, '--ignore-not-found', '-o', 'json'], capture_output=True, text=True, check=False)
        if p.returncode:
            raise RuntimeError('cannot snapshot live Helm resource')
        if not p.stdout.strip():
            continue  # Preserve deliberately absent resources; do not recreate.
        value = json.loads(p.stdout)
        for key in ['uid', 'resourceVersion', 'generation', 'creationTimestamp', 'managedFields']:
            value['metadata'].pop(key, None)
        value.pop('status', None)
        live[kind + '/' + ns + '/' + name] = value
    write(directory / 'baseline.json', live)
    renderer = directory / 'post-renderer.py'
    renderer.write_text('#!/usr/bin/python3\nimport json,sys,yaml\nfrom pathlib import Path\nsnapshot=json.loads((Path(__file__).parent/"desired.json").read_text())\nseen=set()\nfor doc in yaml.safe_load_all(sys.stdin):\n if not doc: continue\n key=doc["kind"]+"/"+doc["metadata"].get("namespace","kubeedge")+"/"+doc["metadata"]["name"]\n if key in snapshot:\n  seen.add(key)\n  print("---")\n  print(yaml.safe_dump(snapshot[key],sort_keys=False))\nassert seen==set(snapshot), "rendered resource set differs from live baseline"\n')
    renderer.chmod(0o700)
    return chart, renderer, live


def upgrade(release, directory, chart, renderer, desired, values, atomic=False):
    write(directory / 'desired.json', desired)
    write(directory / 'override.json', values)
    cmd = H + ['upgrade', release, str(chart), '-n', 'kubeedge', '--reuse-values',
               '--post-renderer', str(renderer), '-f', str(directory / 'override.json'), '--wait', '--timeout', '180s']
    if atomic:
        cmd += ['--atomic']
    run(cmd + ['--dry-run=server'])
    run(cmd)
    return next(r['revision'] for r in json.loads(run(H + ['list', '-n', 'kubeedge', '-o', 'json'])) if r['name'] == release)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    a = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('root required to protect secret-bearing backups')
    os.umask(0o077)
    ca, old = obj('secret', 'casecret'), obj('secret', 'cloudcoresecret')
    ca_der = base64.b64decode(ca['data']['cadata'])
    old_der = base64.b64decode(old['data']['cloudcoredata'])
    requested = renew(ca_der, base64.b64decode(ca['data']['cakeydata']), old_der, '10.77.0.1')
    if not a.apply:
        print('context:', CONTEXT, '; add CloudHub SAN 10.77.0.1; changed:', requested != old_der)
        return
    if requested == old_der:
        served(ca_der, requested, '10.77.0.1')
        print('VPN CloudHub certificate already verified')
        return
    directory = Path('/var/backups/kubeedge') / ('vpn-cloud-' + str(time.time_ns()))
    directory.mkdir(parents=True, mode=0o700)
    write(directory / 'cloudcoresecret.json', old)
    chart, renderer, baseline = capture_release('cloudcore', directory)
    cmkey = 'ConfigMap/kubeedge/cloudcore'
    config = yaml.safe_load(baseline[cmkey]['data']['cloudcore.yaml'])
    old_addresses = config['modules']['cloudHub']['advertiseAddress']
    # Record the actual live baseline first, so atomic rollback cannot restore
    # stale April Helm values/images over later operator fixes.
    revision = upgrade('cloudcore', directory, chart, renderer, baseline,
                       {'cloudCore': {'modules': {'cloudHub': {'advertiseAddress': old_addresses}}}})
    print('Live-preserving Helm baseline revision:', revision, '; backup:', directory, flush=True)
    desired = copy.deepcopy(baseline)
    addresses = list(dict.fromkeys(old_addresses + ['10.77.0.1']))
    config['modules']['cloudHub']['advertiseAddress'] = addresses
    desired[cmkey]['data']['cloudcore.yaml'] = yaml.safe_dump(config, sort_keys=False)
    desired['Deployment/kubeedge/cloudcore']['spec']['template']['metadata'].setdefault('annotations', {})['edgeai.etrilab/vpn-certificate'] = directory.name
    patch = directory / 'certificate.patch.json'
    write(patch, {'data': {'cloudcoredata': base64.b64encode(requested).decode()}})
    try:
        run(K + ['patch', 'secret', 'cloudcoresecret', '-n', 'kubeedge', '--type=merge', '--patch-file', str(patch)])
        upgrade('cloudcore', directory, chart, renderer, desired,
                {'cloudCore': {'modules': {'cloudHub': {'advertiseAddress': addresses}}}}, atomic=True)
        served(ca_der, requested, '10.77.0.1')
        served(ca_der, requested, '192.168.0.56')
    except BaseException:
        write(patch, {'data': old['data']})
        run(K + ['patch', 'secret', 'cloudcoresecret', '-n', 'kubeedge', '--type=merge', '--patch-file', str(patch)])
        run(H + ['rollback', 'cloudcore', str(revision), '-n', 'kubeedge', '--wait', '--timeout', '180s'])
        run(K + ['rollout', 'restart', 'deploy/cloudcore', '-n', 'kubeedge'])
        served(ca_der, old_der, '192.168.0.56')
        raise
    print('CloudHub VPN/LAN CA and hostname verification passed; CA, existing key and old SANs preserved.')


if __name__ == '__main__':
    main()
