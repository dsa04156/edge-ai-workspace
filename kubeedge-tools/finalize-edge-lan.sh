#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KUBE_CONTEXT="${KUBE_CONTEXT:?set the exact Kubernetes context}"
EDGE_NODE_NAME="${EDGE_NODE_NAME:?set the joined edge node name}"
EDGE_NODE_CLASS="${EDGE_NODE_CLASS:?set EDGE_NODE_CLASS to jetson, jetagx, raspi, or tinker}"
CLOUDCORE_HOST="${CLOUDCORE_HOST:?set the private LAN CloudCore address}"
DRY_RUN="${DRY_RUN:-0}"

python3 "${SCRIPT_DIR}/patch_edgecore_config.py" \
	--node-name "${EDGE_NODE_NAME}" \
	--node-class "${EDGE_NODE_CLASS}" \
	--cloudcore-host "${CLOUDCORE_HOST}" \
	--validate-inputs-only

kubectl config get-contexts -o name | grep -Fxq "${KUBE_CONTEXT}" || {
	echo "unknown Kubernetes context: ${KUBE_CONTEXT}" >&2
	exit 1
}

kubectl --context "${KUBE_CONTEXT}" get node "${EDGE_NODE_NAME}" >/dev/null
kubectl --context "${KUBE_CONTEXT}" wait \
	--for=condition=Ready "node/${EDGE_NODE_NAME}" --timeout=180s

command -v helm >/dev/null 2>&1 || {
	echo "helm is required to verify the CloudCore release" >&2
	exit 1
}
cloudcore_version="$(
	helm list -n kubeedge --filter '^cloudcore$' -o json \
		| python3 -c 'import json, sys; rows=json.load(sys.stdin); print(rows[0]["app_version"] if rows else "")'
)"
kubelet_version="$(
	kubectl --context "${KUBE_CONTEXT}" get node "${EDGE_NODE_NAME}" \
		-o jsonpath='{.status.nodeInfo.kubeletVersion}'
)"
edgecore_version="${kubelet_version##*kubeedge-}"
if [[ -z "${cloudcore_version}" || "${edgecore_version#v}" != "${cloudcore_version#v}" ]]; then
	echo "KubeEdge version mismatch: cloud=${cloudcore_version:-missing} edge=${edgecore_version:-missing}" >&2
	exit 1
fi
echo "KubeEdge version match: ${cloudcore_version}"

labels="$(kubectl --context "${KUBE_CONTEXT}" get node "${EDGE_NODE_NAME}" -o jsonpath='{.metadata.labels}')"
grep -q 'node-role.kubernetes.io/edge' <<<"${labels}" || {
	echo "edge role label missing" >&2
	exit 1
}
grep -q 'node-role.kubernetes.io/agent' <<<"${labels}" || {
	echo "agent role label missing" >&2
	exit 1
}

case "${EDGE_NODE_CLASS}" in
	jetson) hardware_label="jetson" ;;
	jetagx) hardware_label="jetagx" ;;
	raspi) hardware_label="raspi" ;;
	tinker) hardware_label="tinker-edge-r" ;;
	*)
		echo "unsupported edge node class: ${EDGE_NODE_CLASS}" >&2
		exit 1
		;;
esac
if [[ "${DRY_RUN}" != "1" ]]; then
	kubectl --context "${KUBE_CONTEXT}" label node "${EDGE_NODE_NAME}" \
		environment=edge "edge.device/class=${hardware_label}" --overwrite
	kubectl --context "${KUBE_CONTEXT}" label node "${EDGE_NODE_NAME}" \
		edge.device/mapper- 2>/dev/null || true
else
	echo "dry-run: node labels were not changed"
fi

wait_for_pod() {
	local namespace="$1"
	local selector="$2"
	local description="$3"
	kubectl --context "${KUBE_CONTEXT}" -n "${namespace}" wait pod \
		-l "${selector}" \
		--field-selector "spec.nodeName=${EDGE_NODE_NAME}" \
		--for=condition=Ready --timeout=180s >/dev/null || {
		echo "${description} is not Ready on ${EDGE_NODE_NAME}" >&2
		exit 1
	}
}

wait_for_pod kube-system app=flannel "edge Flannel"
wait_for_pod kubeedge kubeedge=edgemesh-agent "EdgeMesh agent"
wait_for_pod kube-system app.kubernetes.io/name=prometheus-node-exporter "node exporter"

kubectl --context "${KUBE_CONTEXT}" get node "${EDGE_NODE_NAME}" -o wide
kubectl --context "${KUBE_CONTEXT}" get pods -A \
	--field-selector "spec.nodeName=${EDGE_NODE_NAME}" -o wide

if command -v jq >/dev/null 2>&1; then
	kubectl --context "${KUBE_CONTEXT}" get --raw \
		'/api/v1/namespaces/default/services/http:state-aggregator:8000/proxy/state/nodes' \
		| jq -e --arg node "${EDGE_NODE_NAME}" 'any(.[]; .hostname == $node)' >/dev/null || {
		echo "state-aggregator does not yet expose ${EDGE_NODE_NAME}" >&2
		exit 1
	}
else
	echo "WARNING: jq missing; state-aggregator identity check skipped" >&2
fi

echo "LAN edge node finalized; run edge-orch/scripts/check-edgecore-node.sh for DNS smoke validation"
