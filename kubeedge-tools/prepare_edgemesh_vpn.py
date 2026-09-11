#!/usr/bin/env python3
"""Add VPN relay advertisement while preserving current Helm resources and PSK."""
import argparse
import copy
import hashlib
import os
import tarfile
import time
from pathlib import Path

import yaml
from prepare_cloud_vpn import capture_release, upgrade


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--agent-chart-archive', type=Path, required=True)
    args = p.parse_args()
    if os.geteuid() != 0:
        raise ValueError('root required for private Helm backups')
    os.umask(0o077)
    directory = Path('/var/backups/kubeedge/edgemesh-vpn-' + str(time.time_ns()))
    directory.mkdir(parents=True, mode=0o700)
    chart, renderer, baseline = capture_release('edgemesh', directory)
    # Helm release Secrets omit dependency chart objects. Restore only the
    # agent chart; all rendered resources still pass through live preservation.
    with tarfile.open(args.agent_chart_archive) as archive:
        for member in archive.getmembers():
            prefix = 'edgemesh/charts/agent/'
            if not member.name.startswith(prefix) or not member.isfile():
                continue
            relative = Path(member.name[len('edgemesh/'):])
            if '..' in relative.parts or relative.is_absolute():
                raise ValueError('invalid chart archive path')
            target = chart / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(archive.extractfile(member).read())
            target.chmod(0o600)
    print('Dependency archive SHA256:', hashlib.sha256(args.agent_chart_archive.read_bytes()).hexdigest(), flush=True)
    key = 'ConfigMap/kubeedge/edgemesh-agent-cfg'
    config = yaml.safe_load(baseline[key]['data']['edgemesh-agent.yaml'])
    relays = config['modules']['edgeTunnel']['relayNodes']
    relay = next(r for r in relays if r['nodeName'] == 'etri-ser0001-cg0msb')
    if '10.77.0.1' in relay['advertiseAddress']:
        print('VPN relay already configured')
        return
    print('Add relay 10.77.0.1 preserving existing addresses; apply:', args.apply, flush=True)
    if not args.apply:
        return
    revision = upgrade('edgemesh', directory, chart, renderer, baseline, {'agent': {'relayNodes': copy.deepcopy(relays)}})
    print('Live baseline revision:', revision, '; private backup:', directory, flush=True)
    desired = copy.deepcopy(baseline)
    relay['advertiseAddress'].append('10.77.0.1')
    desired[key]['data']['edgemesh-agent.yaml'] = yaml.safe_dump(config, sort_keys=False)
    # Configuration is restarted one node at a time after the network cutover.
    # No PSK or image mutation; operator deletes exact agent Pods after checks.
    ds = desired['DaemonSet/kubeedge/edgemesh-agent']
    ds['spec']['updateStrategy'] = {'type': 'OnDelete'}
    ds['spec']['template']['metadata'].setdefault('annotations', {})['edgeai.etrilab/vpn-relay'] = directory.name
    revision = upgrade('edgemesh', directory, chart, renderer, desired, {'agent': {'relayNodes': relays}}, atomic=True)
    print('VPN relay Helm revision:', revision, '; agents await per-node restart')


if __name__ == '__main__':
    main()
