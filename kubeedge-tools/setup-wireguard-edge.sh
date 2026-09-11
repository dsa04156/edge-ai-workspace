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
WG_ADDRESS="${WG_ADDRESS:?set WG_ADDRESS, for example 10.77.0.3/32}"
CLOUD_PUBLIC_KEY="${CLOUD_PUBLIC_KEY:?set CLOUD_PUBLIC_KEY}"
CLOUD_ENDPOINT="${CLOUD_ENDPOINT:-192.168.0.56:51820}"
WG_ALLOWED_IPS="${WG_ALLOWED_IPS:-10.77.0.0/24}"
WG_DIR="${WG_DIR:-/etc/wireguard}"
WG_CONF="${WG_DIR}/${WG_IF}.conf"
WG_PRIVATE_KEY_FILE="${WG_DIR}/${WG_IF}.privatekey"
WG_PUBLIC_KEY_FILE="${WG_DIR}/${WG_IF}.publickey"

function ensure_root() {
	if [[ "$(id -u)" -ne 0 ]]; then
		echo "please run as root"
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

function write_config() {
	local private_key
	private_key="$(cat "$WG_PRIVATE_KEY_FILE")"

	cat > "$WG_CONF" <<EOF
[Interface]
Address = ${WG_ADDRESS}
PrivateKey = ${private_key}
SaveConfig = false
MTU = ${WG_MTU}

[Peer]
PublicKey = ${CLOUD_PUBLIC_KEY}
Endpoint = ${CLOUD_ENDPOINT}
AllowedIPs = ${WG_ALLOWED_IPS}
PersistentKeepalive = 25
EOF
	chmod 0600 "$WG_CONF"
}

function restart_service() {
	systemctl enable "wg-quick@${WG_IF}"
	if systemctl is-active --quiet "wg-quick@${WG_IF}"; then
		systemctl restart "wg-quick@${WG_IF}"
	else
		systemctl start "wg-quick@${WG_IF}"
	fi
}

function print_summary() {
	echo
	echo "WireGuard edge endpoint is ready."
	echo "interface: ${WG_IF}"
	echo "address:   ${WG_ADDRESS}"
	echo "endpoint:  ${CLOUD_ENDPOINT}"
	echo "allowed:   ${WG_ALLOWED_IPS}"
	echo "public key:"
	cat "$WG_PUBLIC_KEY_FILE"
}

ensure_root
if [[ -e "$WG_CONF" || -L "$WG_CONF" ]]; then
  echo "Preserving existing $WG_CONF. No changes made; use wireguard_peer.py for peer changes."
  exit 0
fi
export WG_IF WG_MTU WG_ADDRESS CLOUD_PUBLIC_KEY CLOUD_ENDPOINT WG_ALLOWED_IPS
python3 - <<'PYVALIDATE'
import ipaddress, os, re, base64
assert len(base64.b64decode(os.environ['CLOUD_PUBLIC_KEY'], validate=True)) == 32
assert re.fullmatch(r'[A-Za-z0-9.-]+:[0-9]{1,5}', os.environ['CLOUD_ENDPOINT'])
assert 1 <= int(os.environ['CLOUD_ENDPOINT'].rsplit(':', 1)[1]) <= 65535
for value in os.environ['WG_ALLOWED_IPS'].split(','):
    assert ipaddress.IPv4Network(value.strip()).prefixlen > 0
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
write_config
restart_service
print_summary
