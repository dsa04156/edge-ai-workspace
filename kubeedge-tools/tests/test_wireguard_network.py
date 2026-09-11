import base64
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_network as host
import networkctl as net
import wireguard_peer as peer
from join_vpn_worker import join_config

KEY1 = base64.b64encode(b'a' * 32).decode()
KEY2 = base64.b64encode(b'b' * 32).decode()
KEY3 = base64.b64encode(b'c' * 32).decode()
CONFIG = f'''# Existing operator config
[Interface]
Address = 10.77.0.1/24
PrivateKey = {KEY3}
SaveConfig = false
PostUp = keep-existing-hook

[Peer]
# existing peer comment
PublicKey = {KEY1}
PresharedKey = {KEY3}
AllowedIPs = 10.77.0.3/32
'''


def test_inventory_reserved_and_duplicate_addresses_fail_closed():
    data = net.load(net.DEFAULT)
    for bad in ['10.77.0.47', '10.77.0.3', '10.96.0.8', '10.77.0.255']:
        changed = copy.deepcopy(data)
        changed['nodes'][1]['vpn_ip'] = bad
        with pytest.raises(ValueError):
            net.validate(changed)


def test_bundle_keeps_tinker_lan_and_all_initial_interfaces_lan():
    data = net.load(net.DEFAULT)
    data['external_endpoint'] = None
    files = net.bundle(data)
    assert files['flannel-interfaces.json']['data']['etri-dev0004-tedger'] == '192.168.0.7'
    assert files['flannel-interfaces.json']['data']['etri-dev0001-jetorn'] == '192.168.0.3'
    assert 'etri-dev0004-tedger.interface.patch.json' not in files
    assert files['routing.json']['lan_return_routes']['etri-dev0004-tedger']['via'] == '192.168.0.56'
    assert files['routing.json']['spoke_allowed_ips'] == ['10.77.0.0/24', '192.168.0.7/32']
    assert files['flannel-edge.patch.json']['spec']['updateStrategy']['type'] == 'OnDelete'
    assert files['plan.json']['applied'] is False
    assert files['plan.json']['blockers']


def test_peer_add_preserves_keys_hooks_comments_and_is_idempotent():
    result = peer.reconcile(CONFIG, KEY2, '10.77.0.4/32')
    assert result.startswith(CONFIG.rstrip())
    assert f'PresharedKey = {KEY3}' in result
    assert peer.reconcile(result, KEY2, '10.77.0.4/32') == result


def test_peer_update_preserves_psk_and_other_blocks():
    source = peer.reconcile(CONFIG, KEY2, '10.77.0.4/32')
    result = peer.reconcile(source, KEY1, '10.77.0.3/32', endpoint='example.org:51820', keepalive=25)
    assert f'PresharedKey = {KEY3}' in result
    assert result.split(f'PublicKey = {KEY2}')[1] == source.split(f'PublicKey = {KEY2}')[1]
    assert peer.reconcile(result, KEY1, '10.77.0.3/32', endpoint='example.org:51820', keepalive=25) == result


@pytest.mark.parametrize('allowed', ['10.77.0.3/32', '10.77.0.0/24', '0.0.0.0/0', '10.77.0.1/32'])
def test_peer_collision_refused(allowed):
    with pytest.raises(ValueError):
        peer.reconcile(CONFIG, KEY2, allowed)


def test_spoke_whole_vpn_allowed_and_saveconfig_rejected():
    spoke = CONFIG.split('[Peer]')[0].replace('10.77.0.1/24', '10.77.0.4/32')
    assert 'AllowedIPs = 10.77.0.0/24' in peer.reconcile(spoke, KEY1, '10.77.0.0/24')
    with pytest.raises(ValueError):
        peer.reconcile(CONFIG.replace('SaveConfig = false', 'SaveConfig = true'), KEY2, '10.77.0.4/32')


def test_sync_failure_restores_disk_and_live_config(tmp_path, monkeypatch):
    path = tmp_path / 'wg0.conf'
    path.write_text(CONFIG)
    path.chmod(0o600)
    calls = []
    def fake(args, input=None):
        calls.append((args, input))
        if args[:2] == ['wg', 'showconf']:
            return CONFIG
        if args[:2] == ['wg', 'pubkey'] or args == ['wg', 'show', 'wg0', 'public-key']:
            return KEY3
        if args[0] == 'ip':
            return '[{"dst":"10.77.0.0/24"}]'
        if args[:2] == ['wg-quick', 'strip']:
            return 'candidate'
        if args[:2] == ['wg', 'syncconf'] and input == 'candidate':
            raise RuntimeError('simulated sync failure')
        return ''
    monkeypatch.setattr(peer, 'run', fake)
    monkeypatch.setattr(peer.os, 'geteuid', lambda: 0)
    with pytest.raises(RuntimeError):
        peer.apply(path, 'wg0', CONFIG, peer.reconcile(CONFIG, KEY2, '10.77.0.4/32'))
    assert path.read_text() == CONFIG
    assert calls[-1][1] == CONFIG
    assert next(tmp_path.glob('*.backup-*')).stat().st_mode & 0o777 == 0o600


def test_unpersisted_live_peer_blocks_before_any_write(tmp_path, monkeypatch):
    path = tmp_path / 'wg0.conf'
    path.write_text(CONFIG)
    live = peer.reconcile(CONFIG, KEY3, '10.77.0.9/32')
    monkeypatch.setattr(peer.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(peer, 'run', lambda *a, **k: live)
    with pytest.raises(ValueError, match='unpersisted'):
        peer.apply(path, 'wg0', CONFIG, peer.reconcile(CONFIG, KEY2, '10.77.0.4/32'))
    assert path.read_text() == CONFIG
    assert list(tmp_path.iterdir()) == [path]


def host_fixture(role):
    data = net.load(net.DEFAULT)
    node = 'etri-dev0001-jetorn' if role == 'edge' else 'etri-ser0002-cgnmsb'
    spec = net.bundle(data)[node + '.host.json']
    files = {
        host.EDGE: yaml.safe_dump({'apiVersion': 'edgecore.config.kubeedge.io/v1alpha2', 'modules': {
            'edged': {'hostnameOverride': node, 'tailoredKubeletConfig': {'clusterDNS': ['169.254.96.16'], 'containerRuntimeEndpoint': 'unix:///run/containerd/containerd.sock'}},
            'edgeHub': {'httpServer': 'old', 'websocket': {'server': 'old'}},
            'edgeStream': {'server': 'old'}, 'serviceBus': {'enable': False}}}),
        host.KUBE: yaml.safe_dump({'current-context': 'worker', 'contexts': [{'name': 'worker', 'context': {'cluster': 'c'}}], 'clusters': [{'name': 'c', 'cluster': {'server': 'old', 'certificate-authority-data': 'preserve'}}], 'users': [{'name': 'u', 'user': {'client-key-data': 'preserve'}}]}),
        Path('/etc/systemd/system/kubelet.service.d/10-kubeadm.conf'): '[Service]\nExecStart=\nExecStart=/usr/bin/kubelet $KUBELET_KUBEADM_ARGS $KUBELET_EXTRA_ARGS\n',
        Path('/etc/wireguard/wg0.conf'): CONFIG,
        Path('/etc/containerd/certs.d/192.168.0.56:5000/hosts.toml'): 'server = "http://192.168.0.56:5000"\n[host."http://192.168.0.56:5000"]\n capabilities = ["pull", "resolve"]\n',
    }
    return spec, files


@pytest.mark.parametrize('role', ['worker', 'edge'])
def test_host_changes_preserve_credentials_runtime_and_are_idempotent(role):
    spec, files = host_fixture(role)
    first = host.changes(spec, files.__getitem__)
    files.update(first)
    second = host.changes(spec, files.__getitem__)
    assert first == second
    if role == 'worker':
        cfg = yaml.safe_load(first[host.KUBE])
        assert cfg['users'][0]['user']['client-key-data'] == 'preserve'
        assert '$KUBELET_EXTRA_ARGS $EDGEAI_NODE_IP_ARGS' in first[host.DROP]
    else:
        cfg = yaml.safe_load(first[host.EDGE])
        assert cfg['modules']['edged']['customInterfaceName'] == 'wg0'
        assert cfg['modules']['edged']['tailoredKubeletConfig']['clusterDNS'] == ['169.254.96.16']
        assert cfg['modules']['serviceBus'] == {'enable': False}
    assert f'PrivateKey = {KEY3}' in first[Path('/etc/wireguard/wg0.conf')]


def test_host_migration_refuses_control_plane():
    spec = net.bundle(net.load(net.DEFAULT))['etri-ser0001-cg0msb.host.json']
    with pytest.raises(ValueError, match='control plane'):
        host.changes(spec)


def test_worker_join_pins_identity_and_ca_without_skip_verification():
    cfg = join_config({'KUBERNETES_VERSION': 'v1.31.14', 'DISCOVERY_CA_HASH': 'sha256:' + 'a' * 64,
                       'NODE_NAME': 'remote-worker-01', 'NODE_VPN_IP': '10.77.0.100', 'CLOUD_VPN_IP': '10.77.0.1'}, 'abcdef.' + 'a' * 16)
    assert cfg['nodeRegistration']['name'] == 'remote-worker-01'
    assert cfg['nodeRegistration']['kubeletExtraArgs'] == [{'name': 'node-ip', 'value': '10.77.0.100'}]
    assert cfg['discovery']['bootstrapToken']['caCertHashes'] == ['sha256:' + 'a' * 64]
    assert 'unsafeSkipCAVerification' not in str(cfg)


def test_edge_patcher_optional_interface_does_not_change_lan_default():
    from patch_edgecore_config import patch_lines
    from test_patch_edgecore_config import V123_CONFIG
    args = ('etri-dev0001-jetorn', '10.77.0.1', 'unix:///run/containerd/containerd.sock')
    lan, _ = patch_lines(V123_CONFIG.splitlines(True), *args)
    assert 'customInterfaceName' not in ''.join(lan)
    vpn, _ = patch_lines(V123_CONFIG.splitlines(True), *args, network_interface='wg0')
    twice, changes = patch_lines(vpn, *args, network_interface='wg0')
    assert vpn == twice and changes == []
    assert ''.join(vpn).count('customInterfaceName: wg0') == 1


def test_render_does_not_reset_an_already_migrated_flannel_node():
    data = net.load(net.DEFAULT)
    name = 'etri-dev0001-jetorn'
    live = {'nodes': [{'name': name, 'flannel_ip': '10.77.0.3', 'ready': 'True'}]}
    result = net.bundle(data, live)
    assert result['flannel-interfaces.json']['data'][name] == 'wg0'
    assert result[name + '.interface.rollback.json']['data'][name] == 'wg0'


def test_host_restart_failure_restores_existing_and_removes_new_files(tmp_path, monkeypatch):
    spec, _ = host_fixture('worker')
    original = tmp_path / 'original.conf'
    original.write_text('before')
    original.chmod(0o640)
    new = tmp_path / 'new.conf'
    monkeypatch.setattr(host, 'ROOT', tmp_path / 'backups')
    monkeypatch.setattr(host, 'preflight', lambda _: 1420)
    failed = []
    calls = []
    def fake(args):
        calls.append(args)
        if args == ['systemctl', 'restart', 'kubelet'] and not failed:
            failed.append(True)
            raise RuntimeError('simulated restart failure')
        return ''
    monkeypatch.setattr(host, 'run', fake)
    with pytest.raises(RuntimeError):
        host.apply(spec, {original: 'after', new: 'new'})
    assert original.read_text() == 'before'
    assert original.stat().st_mode & 0o777 == 0o640
    assert not new.exists()
    state = json.loads(next((tmp_path / 'backups').glob('*/state.json')).read_text())
    assert state['status'] == 'rolled-back'
    assert ['ip', 'link', 'set', 'dev', 'wg0', 'mtu', '1420'] in calls
    assert any(c[0] == 'systemd-run' for c in calls)


def test_setup_scripts_default_preview_does_not_create_config(tmp_path):
    import os
    for name in ['setup-wireguard-cloud.sh', 'setup-wireguard-edge.sh']:
        script = Path(__file__).resolve().parents[1] / name
        result = subprocess.run(['bash', str(script)], env={**os.environ, 'WG_DIR': str(tmp_path / 'vpn')}, capture_output=True, text=True, check=False)
        assert result.returncode == 0
        assert 'Preview only' in result.stdout
        assert not (tmp_path / 'vpn').exists()


def test_apiserver_san_addition_preserves_old_addresses_and_ca_config(tmp_path, monkeypatch):
    file = Path(__file__).resolve().parents[2] / 'tools/add-apiserver-san.py'
    spec = importlib.util.spec_from_file_location('san_tool_test', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'EXTRA', '10.77.0.1')
    original = {'apiVersion': 'kubeadm.k8s.io/v1beta4', 'kind': 'ClusterConfiguration', 'certificatesDir': '/etc/kubernetes/pki', 'apiServer': {'certSANs': ['10.254.192.217']}}
    updated, _staged = module.configuration(original, ['192.168.0.56', 'kubernetes'], tmp_path)
    assert set(updated['apiServer']['certSANs']) == {'10.77.0.1', '192.168.0.56', '10.254.192.217', 'kubernetes'}
    assert updated['certificatesDir'] == '/etc/kubernetes/pki'
    assert original['apiServer']['certSANs'] == ['10.254.192.217']


def test_packaged_kubelet_unit_and_vpn_registry_precedence():
    spec, files = host_fixture('worker')
    packaged = Path('/usr/lib/systemd/system/kubelet.service.d/10-kubeadm.conf')
    files[packaged] = files.pop(Path('/etc/systemd/system/kubelet.service.d/10-kubeadm.conf'))
    def read(path):
        if path not in files:
            raise FileNotFoundError(path)
        return files[path]
    changed = host.changes(spec, read)
    registry = host.tomllib.loads(changed[Path('/etc/containerd/certs.d/192.168.0.56:5000/hosts.toml')])
    assert next(iter(registry['host'])) == 'http://10.77.0.1:5000'
    assert registry['server'] == 'http://192.168.0.56:5000'
    assert registry['host']['http://192.168.0.56:5000']['capabilities'] == ['pull', 'resolve']
    assert 'Requires=wg-quick@wg0.service' in changed[Path('/etc/systemd/system/kubelet.service.d/35-edgeai-vpn-order.conf')]


def test_mixed_transit_finalization_preserves_reserved_peer_and_keys():
    from prepare_vpn_routes import edit_config
    original = CONFIG + f'\n[Peer]\nPublicKey = {KEY2}\nAllowedIPs = 10.77.0.47/32\n'
    mixed = edit_config(original, hub=True, final=False)
    assert '192.168.0.3/32' in mixed and 'Table = off' in mixed
    assert edit_config(mixed, hub=True, final=False) == mixed
    final = edit_config(mixed, hub=True, final=True)
    assert '192.168.0.3/32' not in final and 'Table = off' not in final
    assert final.split(f'PublicKey = {KEY2}')[1] == original.split(f'PublicKey = {KEY2}')[1]
    assert f'PrivateKey = {KEY3}' in final and f'PresharedKey = {KEY3}' in final
    assert edit_config(final, hub=True, final=True) == final


def test_spoke_finalization_retains_only_tinker_lan_crypto_route():
    from prepare_vpn_routes import edit_config
    spoke = CONFIG.replace('Address = 10.77.0.1/24', 'Address = 10.77.0.3/32').replace('AllowedIPs = 10.77.0.3/32', 'AllowedIPs = 10.77.0.0/24')
    mixed = edit_config(spoke, hub=False, final=False)
    final = edit_config(mixed, hub=False, final=True)
    assert 'AllowedIPs = 10.77.0.0/24, 192.168.0.7/32' in final
    assert '192.168.0.56/32' not in final
    assert 'Table = off' not in final
    with pytest.raises(ValueError, match='custom policy'):
        edit_config(spoke.replace('SaveConfig = false', 'Table = 123'), hub=False, final=False)
    with pytest.raises(ValueError, match='SaveConfig'):
        edit_config(spoke.replace('SaveConfig = false', 'SaveConfig = true'), hub=False, final=False)
