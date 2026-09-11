#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EDGECORE_CONFIG="${EDGECORE_CONFIG:-/etc/kubeedge/config/edgecore.yaml}"
EDGE_NODE_NAME="${EDGE_NODE_NAME:?set EDGE_NODE_NAME, for example etri-dev0004-raspi5}"
EDGE_NODE_CLASS="${EDGE_NODE_CLASS:?set EDGE_NODE_CLASS to jetson or raspi}"
CLOUDCORE_HOST="${CLOUDCORE_HOST:?set CLOUDCORE_HOST to the private LAN address}"

if [[ "$(id -u)" -ne 0 ]]; then
	echo "please run as root: sudo -E ./patch-edge.sh" >&2
	exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
	echo "python3 is required to patch EdgeCore YAML safely" >&2
	exit 1
fi

actual_hostname="$(hostnamectl --static)"
if [[ "${actual_hostname}" != "${EDGE_NODE_NAME}" ]]; then
	echo "hostname mismatch: host=${actual_hostname} requested=${EDGE_NODE_NAME}" >&2
	exit 1
fi

python3 "${SCRIPT_DIR}/patch_edgecore_config.py" \
	--config "${EDGECORE_CONFIG}" \
	--node-name "${EDGE_NODE_NAME}" \
	--node-class "${EDGE_NODE_CLASS}" \
	--cloudcore-host "${CLOUDCORE_HOST}"

systemctl restart edgecore
systemctl status edgecore --no-pager -n 60
