#!/usr/bin/env bash
set -Eeuo pipefail

# =========================
# Config
# =========================
NAMESPACE="${NAMESPACE:-net-test}"
IMAGE="${IMAGE:-nicolaka/netshoot:v0.15}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-300s}"
CLEANUP="${CLEANUP:-0}"
DNS_NAME="${DNS_NAME:-kubernetes.default.svc.cluster.local}"
HTTP_PORT="${HTTP_PORT:-8080}"

# =========================
# Input
# =========================
if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is required." >&2
  exit 1
fi

if [[ $# -lt 2 ]]; then
  cat >&2 <<EOF
Usage:
  $0 <node1> <node2> [node3 ...]

Example:
  $0 etri-ser0001-cg0msb etri-ser0002-cgnmsb etri-dev0001-jetson etri-dev0002-raspi5

Optional env:
  NAMESPACE=net-test
  IMAGE=nicolaka/netshoot:v0.15
  WAIT_TIMEOUT=300s
  CLEANUP=1
EOF
  exit 1
fi

NODES=("$@")

# =========================
# Counters / helpers
# =========================
PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
RUN_ID="$(date +%s)-$$"

declare -a PASS_MESSAGES=()
declare -a WARN_MESSAGES=()
declare -a FAIL_MESSAGES=()

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  PASS_MESSAGES+=("$*")
  printf 'PASS  %s\n' "$*"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  WARN_MESSAGES+=("$*")
  printf 'WARN  %s\n' "$*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAIL_MESSAGES+=("$*")
  printf 'FAIL  %s\n' "$*"
}

section() {
  printf '\n[%s]\n' "$*"
}

sanitize() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9.-]/-/g'
}

probe_pod_name() {
  local node="$1"
  echo "nettest-$(sanitize "$node")-${RUN_ID}"
}

probe_svc_name() {
  local node="$1"
  echo "nettest-svc-$(sanitize "$node")-${RUN_ID}"
}

delete_ns() {
  kubectl delete ns "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
}

print_message_block() {
  local title="$1"
  shift
  local -a msgs=("$@")

  section "${title}"
  if [[ ${#msgs[@]} -eq 0 ]]; then
    echo "None"
    return
  fi

  local i=1
  for msg in "${msgs[@]}"; do
    printf '%3d. %s\n' "$i" "$msg"
    i=$((i + 1))
  done
}

cleanup() {
  if [[ "${CLEANUP}" == "1" ]]; then
    section "Cleanup"
    delete_ns
    echo "Namespace ${NAMESPACE} deleted."
  else
    echo
    echo "Resources retained in namespace: ${NAMESPACE}"
    echo "To delete later:"
    echo "  kubectl delete ns ${NAMESPACE}"
  fi
}
trap cleanup EXIT

node_exists() {
  kubectl get node "$1" >/dev/null 2>&1
}

node_arch() {
  kubectl get node "$1" -o jsonpath='{.metadata.labels.kubernetes\.io/arch}'
}

pod_ready() {
  kubectl wait --for=condition=Ready "pod/$1" -n "${NAMESPACE}" --timeout="${WAIT_TIMEOUT}" >/dev/null 2>&1
}

pod_ip() {
  kubectl get pod "$1" -n "${NAMESPACE}" -o jsonpath='{.status.podIP}'
}

pod_node() {
  kubectl get pod "$1" -n "${NAMESPACE}" -o jsonpath='{.spec.nodeName}'
}

svc_cluster_ip() {
  kubectl get svc "$1" -n "${NAMESPACE}" -o jsonpath='{.spec.clusterIP}'
}

show_pod_debug() {
  local pod="$1"
  echo "----- describe pod/${pod} -----"
  kubectl describe pod "$pod" -n "${NAMESPACE}" || true
  echo "----- logs pod/${pod} -----"
  kubectl logs "$pod" -n "${NAMESPACE}" --all-containers=true || true
}

show_svc_debug() {
  local svc="$1"
  echo "----- describe svc/${svc} -----"
  kubectl describe svc "$svc" -n "${NAMESPACE}" || true
  echo "----- endpoints ${svc} -----"
  kubectl get endpoints "$svc" -n "${NAMESPACE}" -o wide || true
}

http_get_from_pod() {
  local src_pod="$1"
  local url="$2"
  kubectl exec -n "${NAMESPACE}" "$src_pod" -- sh -lc "curl -fsS --max-time 5 '${url}'" 2>/dev/null || true
}

dns_test_from_pod() {
  local src_pod="$1"
  kubectl exec -n "${NAMESPACE}" "$src_pod" -- sh -lc \
    "getent hosts '${DNS_NAME}' >/dev/null 2>&1 || nslookup '${DNS_NAME}' >/dev/null 2>&1"
}

# =========================
# Validate nodes
# =========================
section "Validate nodes"
for node in "${NODES[@]}"; do
  if ! node_exists "$node"; then
    echo "ERROR: node not found: $node" >&2
    exit 1
  fi
  printf 'Node: %-32s Arch: %s\n' "$node" "$(node_arch "$node")"
done

# =========================
# Namespace setup
# =========================
section "Namespace setup"
kubectl get ns "${NAMESPACE}" >/dev/null 2>&1 || kubectl create ns "${NAMESPACE}" >/dev/null
pass "Namespace ${NAMESPACE} is ready."

# =========================
# Resource creation
# =========================
declare -a PODS=()
declare -a SVCS=()
declare -A POD_FOR_NODE
declare -A SVC_FOR_NODE

section "Create probe pods and services"

for node in "${NODES[@]}"; do
  pod="$(probe_pod_name "$node")"
  svc="$(probe_svc_name "$node")"
  safe_node="$(sanitize "$node")"

  PODS+=("$pod")
  SVCS+=("$svc")
  POD_FOR_NODE["$node"]="$pod"
  SVC_FOR_NODE["$node"]="$svc"

  cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${pod}
  namespace: ${NAMESPACE}
  labels:
    app: nettest-probe
    nettest/node: ${safe_node}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${node}
  containers:
    - name: tools
      image: ${IMAGE}
      imagePullPolicy: IfNotPresent
      command:
        - /bin/sh
        - -lc
        - |
          mkdir -p /www
          echo "node=${node}" > /www/index.html
          python3 -m http.server ${HTTP_PORT} -d /www
EOF

  cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Service
metadata:
  name: ${svc}
  namespace: ${NAMESPACE}
spec:
  selector:
    nettest/node: ${safe_node}
  ports:
    - name: http
      port: ${HTTP_PORT}
      targetPort: ${HTTP_PORT}
EOF

  echo "Created pod=${pod}, svc=${svc}, node=${node}"
done

# =========================
# Wait for pods
# =========================
section "Wait for pod readiness"
READY_OK=1
for pod in "${PODS[@]}"; do
  if pod_ready "$pod"; then
    pass "${pod} is Ready."
  else
    READY_OK=0
    fail "${pod} did not become Ready within ${WAIT_TIMEOUT}"
    show_pod_debug "$pod"
  fi
done

echo
kubectl get pods -n "${NAMESPACE}" -o wide
echo
kubectl get svc -n "${NAMESPACE}" -o wide

if [[ "${READY_OK}" != "1" ]]; then
  section "Summary"
  printf 'PASS=%d WARN=%d FAIL=%d\n' "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}"
  print_message_block "Failure details" "${FAIL_MESSAGES[@]}"
  print_message_block "Warning details" "${WARN_MESSAGES[@]}"
  exit 2
fi

# =========================
# Collect pod/service info
# =========================
declare -A POD_IP
declare -A POD_NODE
declare -A SVC_IP

section "Collected resource info"
for node in "${NODES[@]}"; do
  pod="${POD_FOR_NODE[$node]}"
  svc="${SVC_FOR_NODE[$node]}"

  POD_IP["$pod"]="$(pod_ip "$pod")"
  POD_NODE["$pod"]="$(pod_node "$pod")"
  SVC_IP["$svc"]="$(svc_cluster_ip "$svc")"

  printf 'Node: %-32s Pod: %-45s PodIP: %-15s Svc: %-45s ClusterIP: %s\n' \
    "$node" "$pod" "${POD_IP[$pod]}" "$svc" "${SVC_IP[$svc]}"
done

# =========================
# DNS check
# =========================
section "DNS test"
for src_pod in "${PODS[@]}"; do
  if dns_test_from_pod "$src_pod"; then
    pass "${src_pod} resolves ${DNS_NAME}"
  else
    fail "${src_pod} failed to resolve ${DNS_NAME}"
  fi
done

# =========================
# Self tests
# =========================
section "Self tests"
for node in "${NODES[@]}"; do
  src_pod="${POD_FOR_NODE[$node]}"
  self_pod_ip="${POD_IP[$src_pod]}"
  self_svc="${SVC_FOR_NODE[$node]}"

  body="$(http_get_from_pod "$src_pod" "http://${self_svc}:${HTTP_PORT}/")"
  if grep -q "node=${node}" <<<"${body}"; then
    pass "${src_pod} -> self Service (${self_svc})"
  else
    fail "${src_pod} -> self Service (${self_svc}) failed"
    show_svc_debug "$self_svc"
  fi

  body="$(http_get_from_pod "$src_pod" "http://${self_pod_ip}:${HTTP_PORT}/")"
  if grep -q "node=${node}" <<<"${body}"; then
    pass "${src_pod} -> self PodIP (${self_pod_ip})"
  else
    fail "${src_pod} -> self PodIP (${self_pod_ip}) failed"
  fi
done

# =========================
# Full mesh tests
# =========================
section "Cross-node full-mesh tests"

printf '%-32s | %-32s | %-7s | %-7s\n' "FROM_NODE" "TO_NODE" "SERVICE" "POD_IP"
printf -- '%.0s-' {1..32}; printf -- '-+-'; printf -- '%.0s-' {1..32}; printf -- '-+-'; printf -- '%.0s-' {1..7}; printf -- '-+-'; printf -- '%.0s-' {1..7}; printf '\n'

for src_node in "${NODES[@]}"; do
  src_pod="${POD_FOR_NODE[$src_node]}"

  for dst_node in "${NODES[@]}"; do
    [[ "${src_node}" == "${dst_node}" ]] && continue

    dst_pod="${POD_FOR_NODE[$dst_node]}"
    dst_pod_ip="${POD_IP[$dst_pod]}"
    dst_svc="${SVC_FOR_NODE[$dst_node]}"

    svc_ok="FAIL"
    ip_ok="FAIL"

    body="$(http_get_from_pod "$src_pod" "http://${dst_svc}:${HTTP_PORT}/")"
    if grep -q "node=${dst_node}" <<<"${body}"; then
      svc_ok="PASS"
      pass "${src_node} -> ${dst_node} via Service (${dst_svc})"
    else
      fail "${src_node} -> ${dst_node} via Service (${dst_svc})"
      show_svc_debug "$dst_svc"
    fi

    body="$(http_get_from_pod "$src_pod" "http://${dst_pod_ip}:${HTTP_PORT}/")"
    if grep -q "node=${dst_node}" <<<"${body}"; then
      ip_ok="PASS"
      pass "${src_node} -> ${dst_node} via PodIP (${dst_pod_ip})"
    else
      fail "${src_node} -> ${dst_node} via PodIP (${dst_pod_ip})"
    fi

    printf '%-32s | %-32s | %-7s | %-7s\n' "$src_node" "$dst_node" "$svc_ok" "$ip_ok"
  done
done

# =========================
# Optional ping matrix
# =========================
section "Optional ICMP ping matrix"
printf '%-32s | %-32s | %-7s\n' "FROM_NODE" "TO_NODE" "PING"
printf -- '%.0s-' {1..32}; printf -- '-+-'; printf -- '%.0s-' {1..32}; printf -- '-+-'; printf -- '%.0s-' {1..7}; printf '\n'

for src_node in "${NODES[@]}"; do
  src_pod="${POD_FOR_NODE[$src_node]}"

  for dst_node in "${NODES[@]}"; do
    [[ "${src_node}" == "${dst_node}" ]] && continue

    dst_pod="${POD_FOR_NODE[$dst_node]}"
    dst_pod_ip="${POD_IP[$dst_pod]}"

    if kubectl exec -n "${NAMESPACE}" "$src_pod" -- ping -c 2 -W 2 "${dst_pod_ip}" >/dev/null 2>&1; then
      pass "${src_node} -> ${dst_node} ICMP ping"
      printf '%-32s | %-32s | %-7s\n' "$src_node" "$dst_node" "PASS"
    else
      warn "${src_node} -> ${dst_node} ICMP ping failed"
      printf '%-32s | %-32s | %-7s\n' "$src_node" "$dst_node" "FAIL"
    fi
  done
done

# =========================
# Route snapshot
# =========================
section "Route snapshot"
for pod in "${PODS[@]}"; do
  echo "----- ${pod} on $(pod_node "$pod") -----"
  kubectl exec -n "${NAMESPACE}" "$pod" -- sh -lc "ip addr; echo; ip route" || true
  echo
done

# =========================
# Summary
# =========================
section "Summary"
printf 'PASS=%d WARN=%d FAIL=%d\n' "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}"

print_message_block "Failure details" "${FAIL_MESSAGES[@]}"
print_message_block "Warning details" "${WARN_MESSAGES[@]}"

if (( FAIL_COUNT > 0 )); then
  exit 2
fi
