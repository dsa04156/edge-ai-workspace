#!/usr/bin/env python3
"""Lower exact existing cluster Pod interfaces without restarting workloads."""
import argparse
import ipaddress
import json
import os
import socket
import subprocess
import time
from pathlib import Path

CIDRS = {'etri-ser0001-cg0msb': '10.244.0.0/24', 'etri-ser0002-cgnmsb': '10.244.8.0/24',
         'etri-dev0001-jetorn': '10.244.2.0/24', 'etri-dev0002-raspi5': '10.244.1.0/24',
         'etri-dev0003-raspi5': '10.244.4.0/24', 'etri-dev0004-tedger': '10.244.3.0/24',
         'etri-dev0005-jetagx': '10.244.6.0/24'}
CRI = ['crictl', '--runtime-endpoint', 'unix:///run/containerd/containerd.sock']


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    node = socket.gethostname().lower()
    network = ipaddress.ip_network(CIDRS[node])
    if os.geteuid() != 0:
        raise ValueError('root required for network namespace inspection')
    host_ns = os.stat('/proc/1/ns/net').st_ino
    entries = []
    host_links = json.loads(run(['ip', '-j', 'link', 'show']))
    links_by_index = {v['ifindex']: v for v in host_links}
    if node == 'etri-dev0001-jetorn':
        # Installed crictl v1.20 speaks removed CRI v1alpha2. Use containerd's
        # local task PIDs and deduplicate exact network namespaces instead.
        pods = [{'id': row[0], 'pid': int(row[1]), 'metadata': {'name': row[0]}}
                for row in (line.split() for line in run(['ctr', '-n', 'k8s.io', 'tasks', 'list']).splitlines()[1:])
                if len(row) == 3 and row[2] == 'RUNNING']
    else:
        pods = json.loads(run(CRI + ['pods', '--state', 'Ready', '-o', 'json']))['items']
    seen = set()
    for pod in pods:
        if 'pid' in pod:
            pid = pod['pid']
        else:
            info = json.loads(run(CRI + ['inspectp', pod['id']]))
            pid = int(info['info']['pid'])
        inode = os.stat('/proc/' + str(pid) + '/ns/net').st_ino
        if inode == host_ns or inode in seen:
            continue
        seen.add(inode)
        prefix = ['nsenter', '-t', str(pid), '-n']
        addr = json.loads(run(prefix + ['ip', '-j', '-4', 'addr', 'show', 'dev', 'eth0']))[0]
        if not any(ipaddress.ip_address(a['local']) in network for a in addr.get('addr_info', [])):
            raise ValueError('unexpected Pod address on ' + pod['id'])
        link = json.loads(run(prefix + ['ip', '-j', 'link', 'show', 'dev', 'eth0']))[0]
        peer = links_by_index[link['link_index']]
        if not peer['ifname'].startswith('veth') or peer.get('master') != 'cni0':
            raise ValueError('unexpected CNI veth')
        entries.append({'pod': pod['metadata']['name'], 'id': pod['id'], 'pid': pid, 'inode': inode,
                        'mtu': link['mtu'], 'peer': peer['ifname'], 'peer_mtu': peer['mtu']})
    print(json.dumps({'node': node, 'pod_count': len(entries), 'target_mtu': 1330, 'apply': args.apply}))
    if not args.apply:
        return
    backup = Path('/var/backups/edgeai-network/pod-mtu-' + str(time.time_ns()))
    backup.mkdir(parents=True, mode=0o700)
    bridge = next((v for v in host_links if v['ifname'] == 'cni0'), None)
    (backup / 'state.json').write_text(json.dumps({'node': node, 'entries': entries, 'bridge': bridge}))
    changed = []
    try:
        for entry in entries:
            if os.stat('/proc/' + str(entry['pid']) + '/ns/net').st_ino != entry['inode']:
                raise ValueError('Pod namespace changed; retry inspection')
            changed.append(entry)
            run(['nsenter', '-t', str(entry['pid']), '-n', 'ip', 'link', 'set', 'dev', 'eth0', 'mtu', '1330'])
            run(['ip', 'link', 'set', 'dev', entry['peer'], 'mtu', '1330'])
        if bridge:
            run(['ip', 'link', 'set', 'dev', 'cni0', 'mtu', '1330'])
    except BaseException:
        for entry in reversed(changed):
            path = '/proc/' + str(entry['pid']) + '/ns/net'
            if os.path.exists(path) and os.stat(path).st_ino == entry['inode']:
                run(['nsenter', '-t', str(entry['pid']), '-n', 'ip', 'link', 'set', 'dev', 'eth0', 'mtu', str(entry['mtu'])])
                run(['ip', 'link', 'set', 'dev', entry['peer'], 'mtu', str(entry['peer_mtu'])])
        if bridge:
            run(['ip', 'link', 'set', 'dev', 'cni0', 'mtu', str(bridge['mtu'])])
        raise
    print('Pod MTUs prepared; workload processes preserved; backup:', backup)


if __name__ == '__main__':
    main()
