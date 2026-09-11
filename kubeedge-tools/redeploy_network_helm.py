#!/usr/bin/env python3
"""Review/apply network values to an existing Helm release, preserving live drift.

The complete matching chart is required (including dependency charts). Private
release backups stay under /var/backups/kubeedge. Default is server dry-run.
"""
import argparse
import copy
import json
import os
import time
from pathlib import Path

import yaml
from prepare_cloud_vpn import H, capture_release, run, upgrade, write

ROOT = Path(__file__).resolve().parent


def desired_network(release, baseline, values):
    desired = copy.deepcopy(baseline)
    if release == 'cloudcore':
        key, file = 'ConfigMap/kubeedge/cloudcore', 'cloudcore.yaml'
        cfg = yaml.safe_load(desired[key]['data'][file])
        before = cfg['modules']['cloudHub']['advertiseAddress']
        after = values['cloudCore']['modules']['cloudHub']['advertiseAddress']
        if not set(before) <= set(after) or '10.77.0.1' not in after:
            raise ValueError('network values must retain live addresses and the VPN SAN')
        cfg['modules']['cloudHub']['advertiseAddress'] = after
    else:
        key, file = 'ConfigMap/kubeedge/edgemesh-agent-cfg', 'edgemesh-agent.yaml'
        cfg = yaml.safe_load(desired[key]['data'][file])
        before = cfg['modules']['edgeTunnel']['relayNodes']
        after = values['agent']['relayNodes']
        mapping = {r['nodeName']: set(r['advertiseAddress']) for r in after}
        if any(not set(r['advertiseAddress']) <= mapping.get(r['nodeName'], set()) for r in before):
            raise ValueError('network values must retain live relays and their addresses')
        if '10.77.0.1' not in mapping.get('etri-ser0001-cg0msb', set()):
            raise ValueError('VPN relay missing')
        ds = desired['DaemonSet/kubeedge/edgemesh-agent']
        images = [c['image'] for c in ds['spec']['template']['spec']['containers']]
        if values['agent']['image'] not in images:
            raise ValueError('image differs from live; image upgrade is outside network redeployment')
        cfg['modules']['edgeTunnel']['relayNodes'] = after
    # Preserve the original serialized data if no semantic change is needed.
    if cfg != yaml.safe_load(baseline[key]['data'][file]):
        desired[key]['data'][file] = yaml.safe_dump(cfg, sort_keys=False)
    return desired


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('release', choices=['cloudcore', 'edgemesh'])
    p.add_argument('--chart', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    if os.geteuid() != 0:
        raise ValueError('root required for credential-bearing Helm backups')
    if not a.chart.exists():
        raise ValueError('complete matching local chart required')
    os.umask(0o077)
    directory = Path('/var/backups/kubeedge/network-redeploy-' + str(time.time_ns()))
    directory.mkdir(parents=True, mode=0o700)
    _, renderer, baseline = capture_release(a.release, directory)
    current = json.loads((directory / 'original-release.json').read_text())['chart']['metadata']
    supplied = yaml.safe_load(run(H + ['show', 'chart', str(a.chart.resolve())]))
    if any(current.get(k) != supplied.get(k) for k in ['name', 'version', 'appVersion']):
        raise ValueError('supplied chart metadata differs from installed release')
    filename = 'cloudcore-network-values.yaml' if a.release == 'cloudcore' else 'edgemesh-values.yaml'
    values = yaml.safe_load((ROOT / 'config' / filename).read_text())
    desired = desired_network(a.release, baseline, values)
    write(directory / 'desired.json', desired)
    write(directory / 'override.json', values)
    cmd = H + ['upgrade', a.release, str(a.chart.resolve()), '-n', 'kubeedge', '--reuse-values',
               '--post-renderer', str(renderer), '-f', str(directory / 'override.json')]
    run(cmd + ['--dry-run=server'])
    print('Server dry-run passed; context=kubernetes-admin@kubernetes; release:', a.release)
    print('Live images, keys, PSK and non-network settings preserved; private backup:', directory)
    if a.apply:
        # First preserve actual resources so --atomic cannot restore stale values.
        upgrade(a.release, directory, a.chart.resolve(), renderer, baseline, {})
        revision = upgrade(a.release, directory, a.chart.resolve(), renderer, desired, values, atomic=True)
        print('Helm revision:', revision, '; no automatic Pod restart; verify config and restart exact Pods only if needed.')


if __name__ == '__main__':
    main()
