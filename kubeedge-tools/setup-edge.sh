#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

source ./tools.sh

KUBEEDGE_VERSION="${KUBEEDGE_VERSION:?set KUBEEDGE_VERSION explicitly, for example v1.23.0}"

if [[ ! "${KUBEEDGE_VERSION}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	echo "KUBEEDGE_VERSION must look like v1.23.0" >&2
	exit 1
fi

function ensure_root() {
	if [[ "$(id -u)" -ne 0 ]]; then
		echo "please run as root: sudo ./setup-edge.sh"
		exit 1
	fi
}

function install_keadm_binary() {
	if command -v keadm >/dev/null 2>&1; then
		local current_version
		current_version="$(keadm version 2>/dev/null || true)"
		if grep -Fq "${KUBEEDGE_VERSION#v}" <<<"${current_version}"; then
			echo "keadm already matches ${KUBEEDGE_VERSION}: ${current_version}"
			return
		fi
		echo "replace mismatched keadm with ${KUBEEDGE_VERSION}: ${current_version:-unknown}"
	fi

	local arch=$1
	local pkg_arch="amd64"
	if [[ "$arch" == "arm64" ]]; then
		pkg_arch="arm64"
	fi

	local url="https://github.com/kubeedge/kubeedge/releases/download/${KUBEEDGE_VERSION}/keadm-${KUBEEDGE_VERSION}-linux-${pkg_arch}.tar.gz"
	local tmp_dir
	local archive
	tmp_dir="$(mktemp -d -t keadm-install.XXXXXXXX)"
	archive="${tmp_dir}/keadm-${KUBEEDGE_VERSION}-linux-${pkg_arch}.tar.gz"

	echo "download keadm: $url"
	wget -O "$archive" "$url"
	tar -xzf "$archive" -C "$tmp_dir"
	local -a keadm_candidates=()
	mapfile -t keadm_candidates < <(
		find "$tmp_dir" -type f -path '*/keadm/keadm' -print
	)
	if [[ "${#keadm_candidates[@]}" -ne 1 ]]; then
		echo "expected exactly one extracted keadm binary, found ${#keadm_candidates[@]}" >&2
		exit 1
	fi
	install -m 0755 "${keadm_candidates[0]}" /usr/local/bin/keadm
	rm -rf "$tmp_dir"
}

ensure_root
arch_to_toolarch $arch
install_crictl
install_cni
load_flannel_image
load_kubeedge_pause_image
load_nginx_image

time_is_synchronized=0
if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" == "yes" ]] \
	|| systemctl is-active --quiet ntp 2>/dev/null; then
	time_is_synchronized=1
fi
if [[ "${time_is_synchronized}" != "1" ]] && ! command -v ntpdate >/dev/null 2>&1; then
	if command -v apt-get >/dev/null 2>&1; then
		apt-get update
		DEBIAN_FRONTEND=noninteractive apt-get install -y ntpdate
	elif command -v yum >/dev/null 2>&1; then
		yum install -y ntpdate
	fi
fi

install_keadm_binary "$toolarch"
if [[ "${time_is_synchronized}" == "1" ]]; then
	echo "host time is already synchronized"
elif command -v ntpdate >/dev/null 2>&1; then
	echo "synchronize time with cn.pool.ntp.org"
	ntpdate cn.pool.ntp.org
else
	echo "time synchronization is unavailable" >&2
	exit 1
fi
echo "Done!"
