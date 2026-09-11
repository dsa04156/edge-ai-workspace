#!/usr/bin/env python3
"""Read-only network inventory checks and reviewable migration bundle generation.

No command in this module applies Kubernetes or host changes. Use the explicit
host/peer tools and the operations runbook after reviewing a generated bundle.
"""
import argparse
import copy
import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT = Path(__file__).parent / 'config/wireguard-network.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ipv4(value):
    ip = ipaddress.ip_address(value)
    require(ip.version == 4 and not (ip.is_loopback or ip.is_multicast or ip.is_unspecified),
            'expected a unicast IPv4 address')
    return ip


def validate(data):
    require(data['version'] == 1, 'unsupported inventory version')
    require(bool(re.fullmatch(r'[a-zA-Z0-9_.:@-]+', data['context'])), 'invalid context')
    require(bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', data['interface'])), 'invalid interface')
    net = ipaddress.IPv4Network(data['network'])
    require(1280 <= data['mtu'] <= 1420, 'MTU must be between 1280 and 1420')
    for existing in ['10.244.0.0/16', '10.96.0.0/12']:
        require(not net.overlaps(ipaddress.ip_network(existing)), 'VPN overlaps cluster network')
    names, addresses = set(), set(data.get('reserved_ips', []))
    for value in addresses:
        require(ipv4(value) in net, 'reserved address outside VPN')
    lan = set()
    for node in data['nodes']:
        name = node['name']
        require(bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', name)), 'invalid node name')
        require(name not in names, 'duplicate node name')
        names.add(name)
        require(node['role'] in {'control-plane', 'worker', 'edge'}, 'invalid role')
        address = node.get('lan_ip')
        if address:
            require(str(ipv4(address)) not in lan, 'duplicate LAN IP')
            require(ipv4(address) not in net, 'LAN and VPN ranges overlap')
            lan.add(address)
        vpn = node.get('vpn_ip')
        if vpn:
            require(ipv4(vpn) in net and vpn not in {str(net.network_address), str(net.broadcast_address)}, 'invalid VPN host')
            require(vpn not in addresses, 'duplicate or reserved VPN IP')
            addresses.add(vpn)
        else:
            require(bool(address), 'LAN-only node needs a LAN IP')
        if node['role'] == 'edge':
            require(node.get('class') in {'raspi', 'jetson', 'jetagx', 'tinker'}, 'missing edge hardware class')
    require(data['hub'] in names, 'hub absent from inventory')
    hub = next(n for n in data['nodes'] if n['name'] == data['hub'])
    require(hub['role'] == 'control-plane' and hub.get('vpn_ip') and hub.get('lan_ip'), 'invalid hub')
    order = data['migration_order']
    require(len(order) == len(set(order)), 'duplicate migration order')
    require(set(order) == {n['name'] for n in data['nodes'] if n.get('vpn_ip')}, 'migration order must cover VPN nodes exactly')
    endpoint = data.get('external_endpoint')
    if endpoint:
        require(bool(re.fullmatch(r'[a-zA-Z0-9.-]+:[0-9]{1,5}', endpoint)), 'endpoint must be host:port')
        require(1 <= int(endpoint.rsplit(':', 1)[1]) <= 65535, 'invalid endpoint port')
    return data


def load(path):
    return validate(json.loads(Path(path).read_text()))


def kubectl(data, *args):
    return json.loads(subprocess.check_output(
        ['kubectl', '--context', data['context'], '--request-timeout=15s', *args, '-o', 'json'], text=True))


def snapshot(data):
    # Explicit projection: never export Secrets, full kubeconfigs or Helm values.
    nodes = kubectl(data, 'get', 'nodes')['items']
    return {'context': data['context'], 'nodes': [{
        'name': n['metadata']['name'],
        'addresses': n['status'].get('addresses', []),
        'pod_cidr': n['spec'].get('podCIDR'),
        'ready': next((c['status'] for c in n['status']['conditions'] if c['type'] == 'Ready'), 'Unknown'),
        'flannel_ip': n['metadata'].get('annotations', {}).get('flannel.alpha.coreos.com/public-ip'),
        'kernel': n['status']['nodeInfo']['kernelVersion'],
        'kubelet': n['status']['nodeInfo']['kubeletVersion'],
    } for n in nodes]}


def blockers(data, live=None):
    result = []
    if not data.get('external_endpoint'):
        result.append('external_endpoint missing: external join cannot run')
    for n in data['nodes']:
        if not n.get('ssh') and n['name'] != socket.gethostname().split('.')[0].lower():
            result.append(n['name'] + ': SSH access not recorded; no remote mutation permitted')
    if live:
        found = {n['name']: n for n in live['nodes']}
        for n in data['nodes']:
            if n['name'] not in found:
                result.append(n['name'] + ': not registered (new-node onboarding required)')
            elif found[n['name']]['ready'] != 'True':
                result.append(n['name'] + ': not Ready; migration blocked')
    return result


def flannel_patch(data, role):
    flags = '--ip-masq --kube-subnet-mgr'
    if role == 'edge':
        flags += ' --kube-api-url=http://127.0.0.1:10550'
    command = ('set -eu; iface=$(cat "/etc/kube-flannel-network/$NODE_NAME"); '
               'test -n "$iface"; exec /opt/bin/flanneld --iface "$iface" ' + flags)
    return {'spec': {'updateStrategy': {'type': 'OnDelete', 'rollingUpdate': None},
        'template': {'spec': {
            'containers': [{'name': 'kube-flannel', 'command': ['/bin/sh', '-ec'], 'args': [command],
                'env': [{'name': 'NODE_NAME', 'valueFrom': {'fieldRef': {'fieldPath': 'spec.nodeName'}}}],
                'volumeMounts': [{'name': 'network-interfaces', 'mountPath': '/etc/kube-flannel-network', 'readOnly': True}]}],
            'volumes': [{'name': 'network-interfaces', 'configMap': {'name': 'kube-flannel-network-interfaces'}}]
        }}}}


def bundle(data, live=None):
    hub = next(n for n in data['nodes'] if n['name'] == data['hub'])
    initial = {n['name']: n.get('lan_ip') or data['interface'] for n in data['nodes']}
    if live:
        by_name = {n['name']: n for n in live['nodes']}
        for node in data['nodes']:
            observed = by_name.get(node['name'], {}).get('flannel_ip')
            if observed and observed == node.get('vpn_ip'):
                initial[node['name']] = data['interface']
            elif observed:
                require(observed == node.get('lan_ip'), 'unexpected live Flannel address for ' + node['name'])
    files = {
        'plan.json': {'context': data['context'], 'migration_order': data['migration_order'],
                      'blockers': blockers(data, live), 'wireguard_mtu': data['mtu'],
                      'pod_mtu': data['mtu'] - 50, 'applied': False},
        'flannel-interfaces.json': {'apiVersion': 'v1', 'kind': 'ConfigMap',
            'metadata': {'name': 'kube-flannel-network-interfaces', 'namespace': 'kube-system'}, 'data': initial},
        'flannel-cloud.patch.json': flannel_patch(data, 'cloud'),
        'flannel-edge.patch.json': flannel_patch(data, 'edge'),
    }
    if live:
        files['observed.json'] = live
    for n in data['nodes']:
        if not n.get('vpn_ip'):
            continue
        name = n['name']
        files[name + '.interface.patch.json'] = {'data': {name: data['interface']}}
        files[name + '.interface.rollback.json'] = {'data': {name: initial[name]}}
        files[name + '.host.json'] = {
            'node': name, 'role': n['role'], 'vpn_ip': n['vpn_ip'], 'interface': data['interface'],
            'cloud_ip': hub['vpn_ip'], 'mtu': data['mtu'],
            'registry_namespace': hub['lan_ip'] + ':5000',
            'registry_endpoint': 'http://' + hub['vpn_ip'] + ':5000',
        }
    files['routing.json'] = {
        'hub': hub['name'],
        'spoke_allowed_ips': [data['network']] + [n['lan_ip'] + '/32' for n in data['nodes'] if not n.get('vpn_ip')],
        'hub_peer_allowed_ips': {n['name']: n['vpn_ip'] + '/32' for n in data['nodes'] if n.get('vpn_ip') and n['name'] != hub['name']},
        'lan_return_routes': {n['name']: {'destination': data['network'], 'via': hub['lan_ip']} for n in data['nodes'] if not n.get('vpn_ip')},
        'default_route_changed': False,
    }
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=DEFAULT)
    parser.add_argument('action', nargs='?', choices=['plan', 'inspect', 'render'], default='plan')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        data = load(args.inventory)
        live = snapshot(data) if args.live or args.action in {'inspect', 'render'} else None
        if args.action == 'inspect':
            print(json.dumps(live, ensure_ascii=False, indent=2))
            return 0
        files = bundle(data, live)
        if args.action == 'render':
            require(args.output is not None, '--output required')
            require(not args.output.exists(), 'output already exists; select a new directory to preserve prior evidence')
            # Fetch and preserve the LIVE backend options, not a stale repository ConfigMap.
            cfg = kubectl(data, 'get', 'cm', 'kube-flannel-cfg', '-n', 'kube-system')
            original = json.loads(cfg['data']['net-conf.json'])
            require(original['Network'] == '10.244.0.0/16' and original['Backend']['Type'] == 'vxlan', 'unexpected live CNI')
            changed = copy.deepcopy(original)
            changed['Backend']['MTU'] = data['mtu']
            files['flannel-mtu.patch.json'] = {'data': {'net-conf.json': json.dumps(changed)}}
            files['flannel-mtu.rollback.json'] = {'data': {'net-conf.json': cfg['data']['net-conf.json']}}
            for role in ['cloud', 'edge']:
                ds = kubectl(data, 'get', 'ds', f'kube-flannel-{role}-ds', '-n', 'kube-system')
                files[f'flannel-{role}.rollback.json'] = {'spec': {'template': ds['spec']['template'], 'updateStrategy': ds['spec']['updateStrategy']}}
            for release, root, child in [('cloudcore', 'cloudCore', 'cloudHub'), ('edgemesh', 'agent', 'relayNodes')]:
                values = json.loads(subprocess.check_output(['helm', '--kube-context', data['context'], 'get', 'values', release, '-n', 'kubeedge', '-o', 'json'], text=True))
                hub = next(n for n in data['nodes'] if n['name'] == data['hub'])
                if release == 'cloudcore':
                    old = values[root]['modules'][child]['advertiseAddress']
                    new = list(dict.fromkeys(old + [hub['vpn_ip']]))
                    files['cloudcore.values.json'] = {root: {'modules': {child: {'advertiseAddress': new}}}}
                    files['cloudcore.values.rollback.json'] = {root: {'modules': {child: {'advertiseAddress': old}}}}
                else:
                    relays = copy.deepcopy(values[root][child])
                    before = copy.deepcopy(relays)
                    relay = next(n for n in relays if n['nodeName'] == hub['name'])
                    relay['advertiseAddress'] = list(dict.fromkeys(relay['advertiseAddress'] + [hub['vpn_ip']]))
                    files['edgemesh.values.json'] = {root: {child: relays}}
                    files['edgemesh.values.rollback.json'] = {root: {child: before}}
            args.output.mkdir(parents=True, mode=0o700)
            for name, value in files.items():
                (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            print('Review bundle:', args.output)
        print(json.dumps(files['plan.json'], ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        print('ERROR:', str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
