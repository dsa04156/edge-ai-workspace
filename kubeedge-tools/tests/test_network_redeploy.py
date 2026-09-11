import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from redeploy_network_helm import desired_network


def test_flannel_shared_config_matches_inventory_and_preserves_vpn():
    resources = yaml.safe_load((ROOT / 'kustomization.yaml').read_text())['resources']
    docs = [doc for name in resources for doc in yaml.safe_load_all((ROOT / name).read_text())]
    keys = [(d['kind'], d['metadata'].get('namespace'), d['metadata']['name']) for d in docs]
    assert len(keys) == len(set(keys))
    cm = next(d for d in docs if d['metadata']['name'] == 'kube-flannel-cfg')
    assert json.loads(cm['data']['net-conf.json'])['Backend'] == {'Type': 'vxlan', 'MTU': 1380}
    interfaces = next(d['data'] for d in docs if d['metadata']['name'] == 'kube-flannel-network-interfaces')
    inventory = json.loads((ROOT / 'config/wireguard-network.json').read_text())
    assert interfaces == {n['name']: 'wg0' if n['vpn_ip'] else n['lan_ip'] for n in inventory['nodes']}
    for ds in [d for d in docs if d['kind'] == 'DaemonSet']:
        assert ds['spec']['updateStrategy'] == {'type': 'OnDelete'}
        spec = ds['spec']['template']['spec']
        container = spec['containers'][0]
        assert '--iface "$iface"' in container['args'][0]
        assert any(e['name'] == 'NODE_NAME' for e in container['env'])
        assert any(v.get('configMap', {}).get('name') == 'kube-flannel-network-interfaces' for v in spec['volumes'])
        assert ('--kube-api-url=http://127.0.0.1:10550' in container['args'][0]) == ('edge' in ds['metadata']['name'])


@pytest.mark.parametrize('role', ['cloud', 'edge'])
def test_flannel_entrypoint_default_checks_only_from_other_cwd(tmp_path, role):
    fake = tmp_path / 'kubectl'
    log = tmp_path / 'calls.jsonl'
    fake.write_text('#!/usr/bin/env python3\nimport json,os,sys\nwith open(os.environ["CALL_LOG"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n')
    fake.chmod(0o755)
    env = {**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH'], 'CALL_LOG': str(log), 'KUBE_CONTEXT': 'test-context'}
    subprocess.run(['bash', str(ROOT / ('install-flannel-' + role + '.sh'))], cwd=tmp_path, env=env, check=True, capture_output=True)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 1
    assert calls[0][:2] == ['--context', 'test-context']
    assert '--dry-run=server' in calls[0]
    assert str(ROOT / 'config/flannel-interfaces.yaml') in calls[0]


def test_helm_network_preserves_live_psk_image_and_other_config():
    baseline = {'ConfigMap/kubeedge/edgemesh-agent-cfg': {'data': {'edgemesh-agent.yaml': yaml.safe_dump({'modules': {'edgeTunnel': {'enable': True, 'relayNodes': [{'nodeName': 'etri-ser0001-cg0msb', 'advertiseAddress': ['192.168.0.56']}]}, 'edgeProxy': {'enable': True}}})}},
                'ConfigMap/kubeedge/edgemesh-agent-psk': {'data': {'psk': 'private-fixture'}},
                'DaemonSet/kubeedge/edgemesh-agent': {'spec': {'updateStrategy': {'type': 'OnDelete'}, 'template': {'spec': {'containers': [{'image': 'pinned-image'}]}}}}}
    original = copy.deepcopy(baseline)
    values = {'agent': {'image': 'pinned-image', 'relayNodes': [{'nodeName': 'etri-ser0001-cg0msb', 'advertiseAddress': ['192.168.0.56', '10.77.0.1']}]}}
    desired = desired_network('edgemesh', baseline, values)
    assert baseline == original
    for key, value in baseline.items():
        if key != 'ConfigMap/kubeedge/edgemesh-agent-cfg':
            assert desired[key] == value
    assert desired_network('edgemesh', desired, values) == desired
    values['agent']['image'] = 'unexpected-upgrade'
    with pytest.raises(ValueError, match='image differs'):
        desired_network('edgemesh', baseline, values)


def test_cloud_redeploy_rejects_address_loss_and_keeps_runtime_settings():
    cfg = {'modules': {'cloudHub': {'advertiseAddress': ['192.168.0.56', '10.254.192.217'], 'tlsPrivateKeyFile': '/private/key'}, 'dynamicController': {'enable': False}}}
    baseline = {'ConfigMap/kubeedge/cloudcore': {'data': {'cloudcore.yaml': yaml.safe_dump(cfg)}}}
    values = yaml.safe_load((ROOT / 'config/cloudcore-network-values.yaml').read_text())
    desired = desired_network('cloudcore', baseline, values)
    parsed = yaml.safe_load(desired['ConfigMap/kubeedge/cloudcore']['data']['cloudcore.yaml'])
    assert parsed['modules']['dynamicController'] == {'enable': False}
    assert parsed['modules']['cloudHub']['tlsPrivateKeyFile'] == '/private/key'
    values['cloudCore']['modules']['cloudHub']['advertiseAddress'] = ['10.77.0.1']
    with pytest.raises(ValueError, match='retain live addresses'):
        desired_network('cloudcore', baseline, values)
