#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is required." >&2
  exit 1
fi

CHECK_GPU=false
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-gpu)
      CHECK_GPU=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--check-gpu] <node-name>" >&2
      exit 0
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

NODE_NAME="${POSITIONAL[0]:-}"
if [[ -z "${NODE_NAME}" ]]; then
  echo "Usage: $0 [--check-gpu] <node-name>" >&2
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

require_node() {
  kubectl get node "${NODE_NAME}" >/dev/null 2>&1
}

jsonpath() {
  local path="$1"
  kubectl get node "${NODE_NAME}" -o "jsonpath=${path}"
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

  # Allow the pod to finish and then fetch logs. Ignore wait failures because some commands exit very fast.
  kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${pod_name}" --timeout=60s >/dev/null 2>&1 || true
  kubectl logs "${pod_name}" 2>&1 || true
}

section "Node"
if require_node; then
  READY_STATUS="$(kubectl get node "${NODE_NAME}" -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{end}')"
  OS_IMAGE="$(jsonpath '{.status.nodeInfo.osImage}')"
  KERNEL_VERSION="$(jsonpath '{.status.nodeInfo.kernelVersion}')"
  ARCH="$(jsonpath '{.status.nodeInfo.architecture}')"
  INTERNAL_IP="$(kubectl get node "${NODE_NAME}" -o jsonpath='{range .status.addresses[?(@.type=="InternalIP")]}{.address}{end}')"
  printf 'Node: %s\n' "${NODE_NAME}"
  printf '  Ready: %s\n' "${READY_STATUS:-unknown}"
  printf '  OS: %s\n' "${OS_IMAGE:-unknown}"
  printf '  Kernel: %s\n' "${KERNEL_VERSION:-unknown}"
  printf '  Arch: %s\n' "${ARCH:-unknown}"
  printf '  InternalIP: %s\n' "${INTERNAL_IP:-unknown}"
  if [[ "${READY_STATUS}" == "True" ]]; then
    pass "Node is Ready."
  else
    fail "Node is not Ready."
  fi
else
  fail "Node ${NODE_NAME} not found."
  exit 1
fi

section "Cluster DNS"
if kubectl get svc -n kube-system kube-dns >/dev/null 2>&1; then
  pass "kube-dns service exists."
else
  fail "kube-dns service missing."
fi

DNS_ENDPOINTS="$(kubectl get endpoints -n kube-system kube-dns -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || true)"
if [[ -n "${DNS_ENDPOINTS}" ]]; then
  pass "kube-dns endpoints present: ${DNS_ENDPOINTS}"
else
  fail "kube-dns has no endpoints."
fi

section "Node Services"
KUBE_PROXY_POD="$(
  kubectl get pods -n kube-system \
    -o jsonpath="{range .items[?(@.spec.nodeName=='${NODE_NAME}')]}{.metadata.name}{'\n'}{end}" \
    | grep '^kube-proxy-' \
    | head -n 1 || true
)"
if [[ -n "${KUBE_PROXY_POD}" ]]; then
  pass "kube-proxy pod running on node: ${KUBE_PROXY_POD}"
  if kubectl logs -n kube-system "${KUBE_PROXY_POD}" --tail=200 2>/dev/null | grep -q "Failed to execute iptables-restore"; then
    fail "kube-proxy recently logged iptables-restore failure."
  else
    pass "kube-proxy has no recent iptables-restore failure."
  fi
else
  fail "kube-proxy pod not found on node."
fi

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

section "Host Networking"
HOST_NET_OUTPUT="$(run_node_debug "echo DNS_TCP; nc -vz -w 3 ${KUBE_DNS_IP} 53 2>&1 || true; echo ---; echo DNS_CLUSTER; nslookup kubernetes.default.svc.cluster.local ${KUBE_DNS_IP} 2>&1 || true; echo ---; echo MODS; lsmod | grep -E 'br_netfilter|xt_physdev' || true; echo ---; echo SYSCTL; sysctl net.bridge.bridge-nf-call-iptables net.ipv4.ip_forward 2>/dev/null || true")"
printf '%s\n' "${HOST_NET_OUTPUT}"

if grep -q "Connection to ${KUBE_DNS_IP} 53 port \[tcp/domain\] succeeded" <<<"${HOST_NET_OUTPUT}"; then
  pass "Host can reach kube-dns VIP ${KUBE_DNS_IP}:53/tcp."
else
  fail "Host cannot reach kube-dns VIP ${KUBE_DNS_IP}:53/tcp."
fi

if grep -q "^Name:[[:space:]]*kubernetes.default.svc.cluster.local" <<<"${HOST_NET_OUTPUT}"; then
  pass "Host DNS resolves kubernetes.default.svc.cluster.local through kube-dns."
else
  fail "Host DNS failed to resolve kubernetes.default.svc.cluster.local through kube-dns."
fi

if grep -q "br_netfilter" <<<"${HOST_NET_OUTPUT}"; then
  pass "br_netfilter module loaded."
else
  warn "br_netfilter module not detected."
fi

if grep -q "xt_physdev" <<<"${HOST_NET_OUTPUT}"; then
  pass "xt_physdev module loaded."
else
  warn "xt_physdev module not detected."
fi

if grep -q "net.bridge.bridge-nf-call-iptables = 1" <<<"${HOST_NET_OUTPUT}"; then
  pass "bridge-nf-call-iptables is enabled."
else
  warn "bridge-nf-call-iptables is not enabled."
fi

if grep -q "net.ipv4.ip_forward = 1" <<<"${HOST_NET_OUTPUT}"; then
  pass "ip_forward is enabled."
else
  warn "ip_forward is not enabled."
fi

section "Pod DNS"
CHECK_POD="node-join-dns-check-${NODE_NAME//[^a-zA-Z0-9-]/-}"
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
printf '%s\n' "${POD_DNS_OUTPUT}"

if grep -q "Name:[[:space:]]*kubernetes.default.svc.cluster.local" <<<"${POD_DNS_OUTPUT}"; then
  pass "Pod DNS resolves kubernetes.default.svc.cluster.local."
else
  fail "Pod DNS failed for kubernetes.default.svc.cluster.local."
fi

if [[ "${CHECK_GPU}" == "true" ]]; then
  section "GPU"
  GPU_PLATFORM="$(jsonpath '{.metadata.labels.gpu\.platform}')"
  ACCELERATOR_LABEL="$(jsonpath '{.metadata.labels.accelerator}')"

  if [[ "${GPU_PLATFORM:-}" == "server" || "${ACCELERATOR_LABEL:-}" == "nvidia" ]]; then
    GPU_OUTPUT="$(run_node_debug "echo DEV; ls -l /dev/nvidia* 2>/dev/null || true; echo ---; echo SMI; nvidia-smi 2>&1 || true")"
    printf '%s\n' "${GPU_OUTPUT}"

    if grep -q "/dev/nvidia0" <<<"${GPU_OUTPUT}"; then
      pass "Host exposes NVIDIA device files."
    else
      fail "Host does not expose NVIDIA device files."
    fi

    if grep -q "NVIDIA-SMI" <<<"${GPU_OUTPUT}"; then
      pass "Host nvidia-smi works."
    else
      warn "Host nvidia-smi failed from debug context; verifying via Kubernetes GPU smoke pod."
    fi

    GPU_ALLOCATABLE="$(kubectl get node "${NODE_NAME}" -o jsonpath='{.status.allocatable.nvidia\.com/gpu}' 2>/dev/null || true)"
    if [[ -n "${GPU_ALLOCATABLE}" && "${GPU_ALLOCATABLE}" != "0" ]]; then
      pass "Kubernetes advertises nvidia.com/gpu=${GPU_ALLOCATABLE}."
    else
      fail "Kubernetes does not advertise usable GPU on this node."
    fi

    if [[ -n "${GPU_ALLOCATABLE}" && "${GPU_ALLOCATABLE}" != "0" ]]; then
      GPU_SMOKE_POD="node-join-gpu-check-${NODE_NAME//[^a-zA-Z0-9-]/-}"
      cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${GPU_SMOKE_POD}
  namespace: default
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${NODE_NAME}
  tolerations:
    - operator: Exists
  containers:
    - name: cuda
      image: nvcr.io/nvidia/cuda:12.4.1-base-ubuntu22.04
      command: ["nvidia-smi"]
      resources:
        limits:
          nvidia.com/gpu: 1
EOF

      CLEANUP_PODS+=("${GPU_SMOKE_POD}")

      kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${GPU_SMOKE_POD}" --timeout=180s >/dev/null 2>&1 || true
      GPU_SMOKE_OUTPUT="$(kubectl logs "${GPU_SMOKE_POD}" 2>&1 || true)"
      GPU_SMOKE_PHASE="$(kubectl get pod "${GPU_SMOKE_POD}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
      GPU_SMOKE_EVENTS="$(kubectl describe pod "${GPU_SMOKE_POD}" 2>/dev/null || true)"
      printf '%s\n' "${GPU_SMOKE_OUTPUT}"

      if grep -q "NVIDIA-SMI" <<<"${GPU_SMOKE_OUTPUT}"; then
        pass "GPU smoke pod executed nvidia-smi successfully."
      elif [[ "${GPU_SMOKE_PHASE}" == "Pending" ]] && grep -q "Insufficient nvidia.com/gpu" <<<"${GPU_SMOKE_EVENTS}"; then
        warn "GPU smoke pod is pending because GPUs are already in use; run the script before scheduling GPU workloads for a full validation."
      else
        fail "GPU smoke pod failed to execute nvidia-smi."
      fi
    fi
  else
    warn "Node is not marked as an NVIDIA server node; GPU checks skipped."
  fi
else
  section "GPU"
  warn "GPU checks skipped by default. Re-run with --check-gpu to validate GPU exposure and run a GPU smoke pod."
fi

section "Summary"
printf 'PASS=%d WARN=%d FAIL=%d\n' "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 2
fi
