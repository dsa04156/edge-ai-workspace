#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is required." >&2
  exit 1
fi

NODE_NAME="${1:-}"
if [[ -z "${NODE_NAME}" ]]; then
  echo "Usage: $0 <edge-node-name>" >&2
  exit 1
fi

DEBUG_IMAGE="${DEBUG_IMAGE:-busybox:latest}"
KUBE_DNS_IP="${KUBE_DNS_IP:-10.96.0.10}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
declare -a CLEANUP_PODS=()

delete_pod() {
  local pod="$1"
  kubectl delete pod "${pod}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl wait --for=delete "pod/${pod}" --timeout=30s >/dev/null 2>&1 || true
}

cleanup() {
  local pod
  for pod in "${CLEANUP_PODS[@]:-}"; do
    delete_pod "${pod}"
  done
}

trap cleanup EXIT

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf 'PASS  %s\n' "$*"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf 'WARN  %s\n' "$*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf 'FAIL  %s\n' "$*"
}

section() {
  printf '\n[%s]\n' "$*"
}

run_node_debug() {
  local debug_cmd="$1"
  local create_output pod_name

  create_output="$(kubectl debug "node/${NODE_NAME}" --image="${DEBUG_IMAGE}" -- chroot /host sh -lc "${debug_cmd}" 2>&1)"
  pod_name="$(printf '%s\n' "${create_output}" | awk '/Creating debugging pod/{print $4}' | tail -n 1)"

  if [[ -z "${pod_name}" ]]; then
    printf '%s\n' "${create_output}" >&2
    return 1
  fi

  CLEANUP_PODS+=("${pod_name}")
  kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${pod_name}" --timeout=60s >/dev/null 2>&1 || true
  kubectl logs "${pod_name}" 2>&1 || true
}

section "Node"
kubectl get node "${NODE_NAME}" >/dev/null 2>&1 || { fail "Node ${NODE_NAME} not found."; exit 1; }
READY_STATUS="$(kubectl get node "${NODE_NAME}" -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{end}')"
ROLES="$(kubectl get node "${NODE_NAME}" -o jsonpath='{.metadata.labels}' | tr ',' '\n' | grep 'node-role.kubernetes.io/' || true)"
OS_IMAGE="$(kubectl get node "${NODE_NAME}" -o jsonpath='{.status.nodeInfo.osImage}')"
KERNEL_VERSION="$(kubectl get node "${NODE_NAME}" -o jsonpath='{.status.nodeInfo.kernelVersion}')"
ARCH="$(kubectl get node "${NODE_NAME}" -o jsonpath='{.status.nodeInfo.architecture}')"
printf 'Node: %s\n' "${NODE_NAME}"
printf '  Ready: %s\n' "${READY_STATUS:-unknown}"
printf '  OS: %s\n' "${OS_IMAGE:-unknown}"
printf '  Kernel: %s\n' "${KERNEL_VERSION:-unknown}"
printf '  Arch: %s\n' "${ARCH:-unknown}"
printf '  Roles:\n%s\n' "${ROLES:-  none}"

[[ "${READY_STATUS}" == "True" ]] && pass "Node is Ready." || fail "Node is not Ready."
if grep -q 'node-role.kubernetes.io/edge' <<<"${ROLES}" || grep -q 'node-role.kubernetes.io/agent' <<<"${ROLES}"; then
  pass "Node is labeled as an edge/agent node."
else
  fail "Node is not labeled as an edge/agent node."
fi

section "CloudCore"
if kubectl get svc -n kubeedge cloudcore >/dev/null 2>&1; then
  pass "cloudcore service exists."
else
  fail "cloudcore service missing."
fi
CLOUDCORE_ENDPOINTS="$(kubectl get endpoints -n kubeedge cloudcore -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || true)"
if [[ -n "${CLOUDCORE_ENDPOINTS}" ]]; then
  pass "cloudcore endpoints present: ${CLOUDCORE_ENDPOINTS}"
else
  fail "cloudcore has no endpoints."
fi

section "Node Services"
EDGEMESH_POD="$(
  kubectl get pods -n kubeedge \
    -o jsonpath="{range .items[?(@.spec.nodeName=='${NODE_NAME}')]}{.metadata.name}{'\n'}{end}" 2>/dev/null \
    | grep '^edgemesh-agent-' \
    | head -n 1 || true
)"
if [[ -n "${EDGEMESH_POD}" ]]; then
  pass "edgemesh-agent pod running on node: ${EDGEMESH_POD}"
else
  warn "edgemesh-agent pod not found on node."
fi

section "Host EdgeCore"
HOST_OUTPUT="$(run_node_debug "echo EDGECORE; systemctl is-active edgecore 2>&1 || true; echo ---; test -f /etc/kubeedge/config/edgecore.yaml && echo edgecore_yaml_present || echo edgecore_yaml_missing; echo ---; grep -n 'server:' /etc/kubeedge/config/edgecore.yaml 2>/dev/null | sed -n '1,20p' || true; echo ---; echo DNS; nc -vz -w 3 ${KUBE_DNS_IP} 53 2>&1 || true; echo ---; echo DNS_CLUSTER; nslookup kubernetes.default.svc.cluster.local ${KUBE_DNS_IP} 2>&1 || true; echo ---; echo MODS; lsmod | grep -E 'br_netfilter|xt_physdev' || true; echo ---; echo SYSCTL; sysctl net.bridge.bridge-nf-call-iptables net.ipv4.ip_forward 2>/dev/null || true")"
printf '%s\n' "${HOST_OUTPUT}"

if grep -q '^active$' <<<"${HOST_OUTPUT}"; then
  pass "edgecore systemd service is active."
else
  fail "edgecore systemd service is not active."
fi

if grep -q 'edgecore_yaml_present' <<<"${HOST_OUTPUT}"; then
  pass "edgecore.yaml exists."
else
  fail "edgecore.yaml missing."
fi

if grep -q 'server:' <<<"${HOST_OUTPUT}"; then
  pass "edgecore.yaml contains upstream server configuration."
else
  fail "edgecore.yaml does not show upstream server configuration."
fi

if grep -q "Connection to ${KUBE_DNS_IP} 53 port \[tcp/domain\] succeeded" <<<"${HOST_OUTPUT}"; then
  pass "Host can reach kube-dns VIP ${KUBE_DNS_IP}:53/tcp."
else
  fail "Host cannot reach kube-dns VIP ${KUBE_DNS_IP}:53/tcp."
fi

if grep -q "^Name:[[:space:]]*kubernetes.default.svc.cluster.local" <<<"${HOST_OUTPUT}"; then
  pass "Host DNS resolves kubernetes.default.svc.cluster.local."
else
  warn "Host DNS did not resolve kubernetes.default.svc.cluster.local in debug context."
fi

if grep -q "br_netfilter" <<<"${HOST_OUTPUT}"; then
  pass "br_netfilter module loaded."
else
  warn "br_netfilter module not detected."
fi

if grep -q "xt_physdev" <<<"${HOST_OUTPUT}"; then
  pass "xt_physdev module loaded."
else
  warn "xt_physdev module not detected."
fi

if grep -q "net.bridge.bridge-nf-call-iptables = 1" <<<"${HOST_OUTPUT}"; then
  pass "bridge-nf-call-iptables is enabled."
else
  warn "bridge-nf-call-iptables is not enabled."
fi

if grep -q "net.ipv4.ip_forward = 1" <<<"${HOST_OUTPUT}"; then
  pass "ip_forward is enabled."
else
  warn "ip_forward is not enabled."
fi

section "Pod DNS"
CHECK_POD="edgecore-dns-check-${NODE_NAME//[^a-zA-Z0-9-]/-}"
cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${CHECK_POD}
  namespace: default
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${NODE_NAME}
  containers:
    - name: dns
      image: ${DEBUG_IMAGE}
      command:
        - sh
        - -lc
        - |
          nslookup kubernetes.default.svc.cluster.local
EOF

CLEANUP_PODS+=("${CHECK_POD}")
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${CHECK_POD}" --timeout=90s >/dev/null 2>&1 || true
POD_DNS_OUTPUT="$(kubectl logs "${CHECK_POD}" 2>&1 || true)"
POD_PHASE="$(kubectl get pod "${CHECK_POD}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
POD_DESCRIBE="$(kubectl describe pod "${CHECK_POD}" 2>/dev/null || true)"
printf '%s\n' "${POD_DNS_OUTPUT}"

if grep -q "Name:[[:space:]]*kubernetes.default.svc.cluster.local" <<<"${POD_DNS_OUTPUT}"; then
  pass "Pod DNS resolves kubernetes.default.svc.cluster.local."
elif [[ "${POD_PHASE}" == "Pending" || "${POD_PHASE}" == "ContainerCreating" || -z "${POD_DNS_OUTPUT}" ]]; then
  warn "Pod DNS check did not complete before timeout; verify image pull/runtime on the edge node."
  printf '%s\n' "${POD_DESCRIBE}"
else
  fail "Pod DNS failed for kubernetes.default.svc.cluster.local."
fi

section "Summary"
printf 'PASS=%d WARN=%d FAIL=%d\n' "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 2
fi
