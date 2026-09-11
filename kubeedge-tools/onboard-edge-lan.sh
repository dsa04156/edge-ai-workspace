#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail
set +o xtrace

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EDGE_NODE_NAME="${EDGE_NODE_NAME:?set EDGE_NODE_NAME, for example etri-dev0004-tedger}"
EDGE_NODE_CLASS="${EDGE_NODE_CLASS:?set EDGE_NODE_CLASS to jetson, jetagx, raspi, or tinker}"
CLOUDCORE_HOST="${CLOUDCORE_HOST:?set CLOUDCORE_HOST to the private LAN address}"
KUBEEDGE_VERSION="${KUBEEDGE_VERSION:?set KUBEEDGE_VERSION, for example v1.23.0}"
KUBEEDGE_CGROUP_DRIVER="${KUBEEDGE_CGROUP_DRIVER:-cgroupfs}"
CONFIRM_UNIQUE_NODE="${CONFIRM_UNIQUE_NODE:-}"
DRY_RUN="${DRY_RUN:-0}"

python3 "${SCRIPT_DIR}/patch_edgecore_config.py" \
	--node-name "${EDGE_NODE_NAME}" \
	--node-class "${EDGE_NODE_CLASS}" \
	--cloudcore-host "${CLOUDCORE_HOST}" \
	--validate-inputs-only

if [[ ! "${KUBEEDGE_VERSION}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	echo "KUBEEDGE_VERSION must look like v1.23.0" >&2
	exit 1
fi

case "${KUBEEDGE_CGROUP_DRIVER}" in
	cgroupfs|systemd) ;;
	*) echo "KUBEEDGE_CGROUP_DRIVER must be cgroupfs or systemd" >&2; exit 1 ;;
esac

if [[ "${CONFIRM_UNIQUE_NODE}" != "${EDGE_NODE_NAME}" ]]; then
	echo "set CONFIRM_UNIQUE_NODE=${EDGE_NODE_NAME} after confirming the name is unused" >&2
	exit 1
fi

printf 'LAN edge onboarding plan\n'
printf '  current hostname: %s\n' "$(hostnamectl --static 2>/dev/null || hostname)"
printf '  target hostname:  %s\n' "${EDGE_NODE_NAME}"
printf '  hardware class:   %s\n' "${EDGE_NODE_CLASS}"
printf '  CloudCore:        %s\n' "${CLOUDCORE_HOST}"
printf '  KubeEdge:         %s\n' "${KUBEEDGE_VERSION}"
printf '  cgroup driver:    %s\n' "${KUBEEDGE_CGROUP_DRIVER}"

if [[ "${DRY_RUN}" == "1" ]]; then
	echo "dry-run complete; host was not changed"
	exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
	echo "please run as root with the required variables preserved" >&2
	exit 1
fi

if [[ ! -t 0 ]]; then
	echo "interactive terminal required for hidden join-token input" >&2
	exit 1
fi

if [[ -f /etc/kubeedge/config/edgecore.yaml ]] || systemctl list-unit-files edgecore.service --no-legend 2>/dev/null | grep -q edgecore; then
	echo "existing EdgeCore state detected; diagnose/reconnect instead of running new-node onboarding" >&2
	exit 1
fi

systemctl is-active --quiet containerd || {
	echo "containerd must be active" >&2
	exit 1
}

swap_active=0
if command -v swapon >/dev/null 2>&1; then
	if swapon --noheadings 2>/dev/null | grep -q .; then
		swap_active=1
	fi
elif awk 'NR > 1 { found=1 } END { exit !found }' /proc/swaps 2>/dev/null; then
	swap_active=1
fi
if [[ "${swap_active}" == "1" ]]; then
	echo "swap is active; disable it before EdgeCore onboarding" >&2
	exit 1
fi

if find /etc/cni/net.d -maxdepth 1 -type f -iname '*calico*' -print -quit 2>/dev/null | grep -q .; then
	echo "Calico CNI state detected; do not mix it with the cluster edge Flannel path" >&2
	exit 1
fi

kernel_config_enabled() {
	local symbol="$1"
	local kernel_release
	kernel_release="$(uname -r)"
	if [[ -r /proc/config.gz ]] && zgrep -Fqx "${symbol}=y" /proc/config.gz; then
		return 0
	fi
	[[ -r "/boot/config-${kernel_release}" ]] \
		&& grep -Fqx "${symbol}=y" "/boot/config-${kernel_release}"
}

kernel_feature_usable() {
	local module="$1"
	case "${module}" in
		overlay)
			grep -qw overlay /proc/filesystems
			;;
		br_netfilter)
			[[ -e /proc/sys/net/bridge/bridge-nf-call-iptables ]]
			;;
		vxlan)
			command -v unshare >/dev/null 2>&1 \
				&& command -v ip >/dev/null 2>&1 \
				&& unshare -n sh -c \
					'ip link add vxlan-kubeedge-probe type vxlan id 4094 dstport 4789'
			;;
		*)
			return 1
			;;
	esac
}

load_or_accept_builtin() {
	local module="$1"
	local symbol="$2"
	if modprobe "${module}" 2>/dev/null \
		|| kernel_config_enabled "${symbol}" \
		|| kernel_feature_usable "${module}"; then
		return 0
	fi
	echo "required kernel feature missing: ${symbol} (${module})" >&2
	exit 1
}

require_iptables_match() {
	local match="$1"
	local module="$2"
	modprobe "${module}" 2>/dev/null || true
	iptables -m "${match}" -h >/dev/null 2>&1 || {
		echo "required iptables match is unavailable: ${match} (${module})" >&2
		exit 1
	}
}

command -v iptables >/dev/null 2>&1 || {
	echo "iptables is required by Flannel and EdgeMesh" >&2
	exit 1
}
load_or_accept_builtin overlay CONFIG_OVERLAY_FS
load_or_accept_builtin br_netfilter CONFIG_BRIDGE_NETFILTER
load_or_accept_builtin vxlan CONFIG_VXLAN
for match_module in \
	comment:xt_comment \
	conntrack:xt_conntrack \
	multiport:xt_multiport \
	physdev:xt_physdev \
	statistic:xt_statistic; do
	require_iptables_match "${match_module%%:*}" "${match_module##*:}"
done

hostnamectl set-hostname "${EDGE_NODE_NAME}"
install -m 0644 "${SCRIPT_DIR}/config/kubeedge-edge.modules" /etc/modules-load.d/kubeedge-edge.conf
install -m 0644 "${SCRIPT_DIR}/config/99-kubeedge-edge.conf" /etc/sysctl.d/99-kubeedge-edge.conf
sysctl --system >/dev/null

if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" != "yes" ]]; then
	echo "WARNING: host time is not reported as synchronized" >&2
fi

check_port() {
	local port="$1"
	if command -v nc >/dev/null 2>&1; then
		nc -vz -w 3 "${CLOUDCORE_HOST}" "${port}"
	else
		timeout 3 bash -c "</dev/tcp/${CLOUDCORE_HOST}/${port}"
	fi
}

for port in 10000 10002 10004; do
	check_port "${port}"
done

cd "${SCRIPT_DIR}"
env KUBEEDGE_VERSION="${KUBEEDGE_VERSION}" ./setup-edge.sh
keadm_version_output="$(keadm version 2>&1)"
printf '%s\n' "${keadm_version_output}"
grep -Fq "${KUBEEDGE_VERSION#v}" <<<"${keadm_version_output}" || {
	echo "installed keadm does not match ${KUBEEDGE_VERSION}" >&2
	exit 1
}

KUBEEDGE_JOIN_TOKEN=""
trap 'unset KUBEEDGE_JOIN_TOKEN' EXIT
read -rsp 'KubeEdge join token: ' KUBEEDGE_JOIN_TOKEN
printf '\n'
if [[ -z "${KUBEEDGE_JOIN_TOKEN}" ]]; then
	echo "join token is required" >&2
	exit 1
fi

keadm join \
	--cgroupdriver="${KUBEEDGE_CGROUP_DRIVER}" \
	--cloudcore-ipport="${CLOUDCORE_HOST}:10000" \
	--token="${KUBEEDGE_JOIN_TOKEN}" \
	--kubeedge-version="${KUBEEDGE_VERSION#v}"
unset KUBEEDGE_JOIN_TOKEN

EDGE_NODE_NAME="${EDGE_NODE_NAME}" \
EDGE_NODE_CLASS="${EDGE_NODE_CLASS}" \
CLOUDCORE_HOST="${CLOUDCORE_HOST}" \
	./patch-edge.sh

echo "edge host onboarding finished; run finalize-edge-lan.sh on the cloud operator host"
