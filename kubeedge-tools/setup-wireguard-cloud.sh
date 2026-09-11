#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail
set +o xtrace

case "${1:-}" in
  --apply) ;;
  ""|--check)
    echo "Preview only: creates a NEW WireGuard interface; existing configurations are preserved."
    echo "Apply: $0 --apply (root); existing peers: python3 wireguard_peer.py --help"
    exit 0 ;;
  *) echo "usage: $0 [--check|--apply]" >&2; exit 2 ;;
esac

WG_IF="${WG_IF:-wg0}"
WG_MTU="${WG_MTU:-1380}"
WG_ADDRESS="${WG_ADDRESS:-10.77.0.1/24}"
WG_PORT="${WG_PORT:-51820}"
WG_DIR="${WG_DIR:-/etc/wireguard}"
WG_CONF="${WG_DIR}/${WG_IF}.conf"
WG_PRIVATE_KEY_FILE="${WG_DIR}/${WG_IF}.privatekey"
WG_PUBLIC_KEY_FILE="${WG_DIR}/${WG_IF}.publickey"
SYSCTL_FILE="/etc/sysctl.d/99-kubeedge-wireguard.conf"

function ensure_root() {
	if [[ "$(id -u)" -ne 0 ]]; then
		echo "please run as root: sudo ./setup-wireguard-cloud.sh"
		exit 1
	fi
}

function install_wireguard() {
	if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then
		echo "wireguard already installed"
		return
	fi

	if command -v apt-get >/dev/null 2>&1; then
		apt-get update
		DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard wireguard-tools iptables
	elif command -v dnf >/dev/null 2>&1; then
		dnf install -y wireguard-tools iptables
	elif command -v yum >/dev/null 2>&1; then
		yum install -y wireguard-tools iptables
	else
		echo "unsupported package manager. need apt-get, dnf, or yum"
		exit 1
	fi
}

function ensure_keys() {
	install -d -m 0700 "$WG_DIR"

	if [[ ! -f "$WG_PRIVATE_KEY_FILE" ]]; then
		umask 077
		wg genkey > "$WG_PRIVATE_KEY_FILE"
		wg pubkey < "$WG_PRIVATE_KEY_FILE" > "$WG_PUBLIC_KEY_FILE"
	fi

	wg pubkey < "$WG_PRIVATE_KEY_FILE" > "$WG_PUBLIC_KEY_FILE"
	chmod 0600 "$WG_PRIVATE_KEY_FILE"
	chmod 0644 "$WG_PUBLIC_KEY_FILE"
}

function write_sysctl() {
	cat > "$SYSCTL_FILE" <<EOF
net.ipv4.ip_forward = 1
EOF
	sysctl --system >/dev/null
}

function write_config() {
	if [[ -e "$WG_CONF" ]]; then
		echo "$WG_CONF exists; refusing replacement. Use wireguard_peer.py for peer changes."
		exit 1
	fi

	local private_key
	private_key="$(cat "$WG_PRIVATE_KEY_FILE")"

	cat > "$WG_CONF" <<EOF
[Interface]
Address = ${WG_ADDRESS}
ListenPort = ${WG_PORT}
PrivateKey = ${private_key}
SaveConfig = false
MTU = ${WG_MTU}
PostUp = iptables -A FORWARD -i ${WG_IF} -j ACCEPT
PostUp = iptables -A FORWARD -o ${WG_IF} -j ACCEPT
PostDown = iptables -D FORWARD -i ${WG_IF} -j ACCEPT
PostDown = iptables -D FORWARD -o ${WG_IF} -j ACCEPT

# Add peers after collecting each node public key.
# Example:
# [Peer]
# PublicKey = <external-edge-public-key>
# AllowedIPs = 10.77.0.20/32
EOF
	chmod 0600 "$WG_CONF"
}

function start_service() {
	systemctl enable --now "wg-quick@${WG_IF}"
}

function print_summary() {
	echo
	echo "WireGuard cloud endpoint is ready."
	echo "interface: ${WG_IF}"
	echo "address:   ${WG_ADDRESS}"
	echo "port:      UDP ${WG_PORT}"
	echo "public key:"
	cat "$WG_PUBLIC_KEY_FILE"
	echo
	echo "Next:"
	echo "1. Forward UDP ${WG_PORT} on the site router to this server."
	echo "2. Add peer blocks to ${WG_CONF}, then run:"
	echo "   python3 wireguard_peer.py --help"
	echo "3. Check state with:"
	echo "   wg show ${WG_IF}"
}

ensure_root
if [[ -e "$WG_CONF" || -L "$WG_CONF" ]]; then
  echo "Preserving existing $WG_CONF. No changes made; use wireguard_peer.py for peer changes."
  exit 0
fi
export WG_IF WG_MTU WG_ADDRESS WG_PORT
python3 - <<'PYVALIDATE'
import ipaddress, os, re
assert 1 <= int(os.environ['WG_PORT']) <= 65535, 'invalid port'
assert re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', os.environ['WG_IF']), 'invalid interface'
assert 1280 <= int(os.environ['WG_MTU']) <= 1420, 'invalid MTU'
a = ipaddress.IPv4Interface(os.environ['WG_ADDRESS'])
assert not (a.ip.is_loopback or a.ip.is_multicast or a.ip.is_unspecified), 'invalid address'
PYVALIDATE
install -d -m 0700 "$WG_DIR"
exec 9>"$WG_DIR/.setup.lock"
flock -n 9 || { echo 'another WireGuard initialization is running' >&2; exit 2; }
if [[ -e "$WG_CONF" || -L "$WG_CONF" ]]; then
  echo "Preserving concurrently created $WG_CONF; no changes made."
  exit 0
fi
install_wireguard
ensure_keys
write_sysctl
write_config
start_service
print_summary
