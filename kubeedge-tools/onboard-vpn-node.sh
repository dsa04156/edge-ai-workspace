#!/usr/bin/env bash
# VPN is established separately. No bootstrap/reset or network replacement here.
set -euo pipefail
set +x
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NODE_ROLE="${NODE_ROLE:?worker or edge}"
NODE_NAME="${NODE_NAME:?exact unique hostname}"
NODE_VPN_IP="${NODE_VPN_IP:?unique WireGuard address}"
CLOUD_VPN_IP="${CLOUD_VPN_IP:-10.77.0.1}"
WG_IF="${WG_IF:-wg0}"
case "$NODE_ROLE" in worker|edge) ;; *) echo 'role must be worker or edge' >&2; exit 2;; esac
export NODE_NAME NODE_VPN_IP CLOUD_VPN_IP WG_IF
python3 - <<'PY'
import ipaddress, os, re
assert re.fullmatch(r'[a-z0-9][a-z0-9-]{0,61}[a-z0-9]', os.environ['NODE_NAME'])
assert re.fullmatch(r'[A-Za-z0-9_-]{1,15}', os.environ['WG_IF'])
for key in ['NODE_VPN_IP', 'CLOUD_VPN_IP']:
    value = ipaddress.IPv4Address(os.environ[key])
    assert value.is_private and not value.is_loopback and not value.is_unspecified
PY
case "${1:-}" in
  ''|--check) printf 'Preview: %s joins as %s, node IP %s, hub %s over %s\n' "$NODE_NAME" "$NODE_ROLE" "$NODE_VPN_IP" "$CLOUD_VPN_IP" "$WG_IF"; exit 0;;
  --apply) ;;
  *) echo 'usage: onboard-vpn-node.sh [--check|--apply]' >&2; exit 2;;
esac
[[ $(id -u) == 0 ]] || { echo 'root required' >&2; exit 2; }
[[ "${CONFIRM_UNIQUE_NODE:-}" == "$NODE_NAME" ]] || { echo 'confirm the exact unused node name from the pinned cluster context' >&2; exit 2; }
[[ ! -e /etc/kubernetes/kubelet.conf && ! -e /etc/kubeedge/config/edgecore.yaml ]] || { echo 'existing node state: use migration/recovery, not join' >&2; exit 2; }
systemctl is-active --quiet containerd
[[ $(timedatectl show -p NTPSynchronized --value) == yes ]] || { echo 'synchronized time required' >&2; exit 2; }
[[ $(awk 'END {print NR}' /proc/swaps) == 1 ]] || { echo 'swap must be disabled' >&2; exit 2; }
python3 - <<'PY'
import json, os, socket, subprocess, time
iface = os.environ['WG_IF']
addresses = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'dev', iface]))
assert any(a['local'] == os.environ['NODE_VPN_IP'] for n in addresses for a in n['addr_info']), 'VPN IP missing'
route = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route', 'get', os.environ['CLOUD_VPN_IP']]))
assert route and route[0].get('dev') == iface, 'hub route must use WireGuard'
handshakes = subprocess.check_output(['wg', 'show', iface, 'latest-handshakes'], text=True).splitlines()
assert any(0 < time.time() - int(l.split()[-1]) < 180 for l in handshakes), 'fresh handshake required'
PY
# Functional kernel tests confined to a disposable network namespace.
unshare -n -- sh -eu -c '
ip link add br-vpn-check type bridge
ip link add vx-vpn-check type vxlan id 4094 dstport 4789
iptables -t filter -A FORWARD -m physdev --physdev-is-bridged -j ACCEPT
iptables -t filter -A OUTPUT -p tcp -m multiport --dports 80,443 -m comment --comment vpn-check -j ACCEPT
iptables -t filter -A OUTPUT -m statistic --mode random --probability 0.5 -j ACCEPT
iptables -t nat -A OUTPUT -p tcp --dport 80 -j DNAT --to-destination 192.0.2.1:80
'
if [[ "$NODE_ROLE" == edge ]]; then
  export EDGE_NODE_NAME="$NODE_NAME" CLOUDCORE_HOST="$CLOUD_VPN_IP"
  : "${EDGE_NODE_CLASS:?hardware class required}"
  : "${KUBEEDGE_VERSION:?live-confirmed version required}"
  export EDGE_NODE_CLASS KUBEEDGE_VERSION CONFIRM_UNIQUE_NODE
  bash "$SCRIPT_DIR/onboard-edge-lan.sh"
  python3 "$SCRIPT_DIR/patch_edgecore_config.py" --config /etc/kubeedge/config/edgecore.yaml \
    --node-name "$NODE_NAME" --node-class "$EDGE_NODE_CLASS" --cloudcore-host "$CLOUD_VPN_IP" --network-interface "$WG_IF"
  systemctl restart edgecore
else
  : "${KUBERNETES_VERSION:?live-confirmed Kubernetes version required}"
  : "${DISCOVERY_CA_HASH:?sha256 public discovery CA hash required}"
  export KUBERNETES_VERSION DISCOVERY_CA_HASH
  python3 "$SCRIPT_DIR/join_vpn_worker.py"
fi
echo 'Join submitted. Run node, Flannel, DNS/Service, logs, registry and monitoring checks before declaring completion.'
