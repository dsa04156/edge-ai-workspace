#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl is required." >&2
  exit 1
fi

SOURCE_NODE="${1:-}"
TARGET_NODE="${2:-}"
if [[ -z "${SOURCE_NODE}" || -z "${TARGET_NODE}" ]]; then
  echo "Usage: $0 <source-node> <target-node>" >&2
  exit 1
fi

NAMESPACE="${NAMESPACE:-default}"
IMAGE="${IMAGE:-busybox:latest}"
KUBE_API_DNS="${KUBE_API_DNS:-kubernetes.default.svc.cluster.local}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

RUN_ID="$(date +%s)-$$"
SRC_POD="p2p-src-${RUN_ID}"
DST_POD="p2p-dst-${RUN_ID}"
CLIENT_POD="p2p-client-${RUN_ID}"
SRC_SVC="p2p-src-svc-${RUN_ID}"
DST_SVC="p2p-dst-svc-${RUN_ID}"

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

delete_resource() {
  local kind="$1"
  local name="$2"
  kubectl delete "${kind}" "${name}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl wait --for=delete "${kind}/${name}" -n "${NAMESPACE}" --timeout=30s >/dev/null 2>&1 || true
}

cleanup() {
  delete_resource pod "${CLIENT_POD}"
  delete_resource svc "${SRC_SVC}"
  delete_resource svc "${DST_SVC}"
  delete_resource pod "${SRC_POD}"
  delete_resource pod "${DST_POD}"
}

trap cleanup EXIT

section "Setup"
printf 'Source node: %s\n' "${SOURCE_NODE}"
printf 'Target node: %s\n' "${TARGET_NODE}"

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${SRC_POD}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: ${SRC_POD}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${SOURCE_NODE}
  containers:
    - name: web
      image: ${IMAGE}
      command:
        - sh
        - -lc
        - |
          mkdir -p /www
          echo source-${SOURCE_NODE} > /www/index.html
          httpd -f -p 8080 -h /www
EOF

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${DST_POD}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: ${DST_POD}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${TARGET_NODE}
  containers:
    - name: web
      image: ${IMAGE}
      command:
        - sh
        - -lc
        - |
          mkdir -p /www
          echo target-${TARGET_NODE} > /www/index.html
          httpd -f -p 8080 -h /www
EOF

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Service
metadata:
  name: ${SRC_SVC}
  namespace: ${NAMESPACE}
spec:
  selector:
    app.kubernetes.io/name: ${SRC_POD}
  ports:
    - port: 8080
      targetPort: 8080
EOF

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Service
metadata:
  name: ${DST_SVC}
  namespace: ${NAMESPACE}
spec:
  selector:
    app.kubernetes.io/name: ${DST_POD}
  ports:
    - port: 8080
      targetPort: 8080
EOF

kubectl wait --for=condition=Ready "pod/${SRC_POD}" -n "${NAMESPACE}" --timeout=120s >/dev/null
kubectl wait --for=condition=Ready "pod/${DST_POD}" -n "${NAMESPACE}" --timeout=120s >/dev/null
pass "Source and target test pods are Ready."

SRC_POD_IP="$(kubectl get pod "${SRC_POD}" -n "${NAMESPACE}" -o jsonpath='{.status.podIP}')"
DST_POD_IP="$(kubectl get pod "${DST_POD}" -n "${NAMESPACE}" -o jsonpath='{.status.podIP}')"
printf 'Source pod IP: %s\n' "${SRC_POD_IP}"
printf 'Target pod IP: %s\n' "${DST_POD_IP}"

section "Connectivity"
cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${CLIENT_POD}
  namespace: ${NAMESPACE}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: ${SOURCE_NODE}
  containers:
    - name: client
      image: ${IMAGE}
      command:
        - sh
        - -lc
        - |
          set -e
          wget -T 5 -qO- http://${SRC_SVC}:8080/
          echo ---
          wget -T 5 -qO- http://${SRC_POD_IP}:8080/
          echo ---
          wget -T 5 -qO- http://${DST_SVC}:8080/
          echo ---
          wget -T 5 -qO- http://${DST_POD_IP}:8080/
          echo ---
          nslookup ${KUBE_API_DNS}
EOF

kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${CLIENT_POD}" -n "${NAMESPACE}" --timeout=120s >/dev/null 2>&1 || true
CLIENT_PHASE="$(kubectl get pod "${CLIENT_POD}" -n "${NAMESPACE}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
CLIENT_LOGS="$(kubectl logs "${CLIENT_POD}" -n "${NAMESPACE}" 2>&1 || true)"
printf '%s\n' "${CLIENT_LOGS}"

SOURCE_COUNT="$(grep -c "source-${SOURCE_NODE}" <<<"${CLIENT_LOGS}" || true)"
TARGET_COUNT="$(grep -c "target-${TARGET_NODE}" <<<"${CLIENT_LOGS}" || true)"

if [[ "${SOURCE_COUNT}" -ge 1 ]]; then
  pass "Same-node service connectivity works."
else
  fail "Same-node service connectivity failed."
fi

if [[ "${SOURCE_COUNT}" -ge 2 ]]; then
  pass "Same-node direct pod connectivity works."
else
  fail "Same-node direct pod connectivity failed."
fi

if [[ "${TARGET_COUNT}" -ge 1 ]]; then
  pass "Cross-node service connectivity works."
else
  fail "Cross-node service connectivity failed."
fi

if [[ "${TARGET_COUNT}" -ge 2 ]]; then
  pass "Cross-node direct pod connectivity works."
else
  fail "Cross-node direct pod connectivity failed."
fi

if grep -q "Name:[[:space:]]*${KUBE_API_DNS}" <<<"${CLIENT_LOGS}"; then
  pass "Client pod resolves cluster service DNS."
else
  fail "Client pod failed to resolve cluster service DNS."
fi

if [[ "${CLIENT_PHASE}" != "Succeeded" ]]; then
  warn "Client pod phase is ${CLIENT_PHASE:-unknown}; inspect logs above if a connectivity failure was reported."
fi

section "Summary"
printf 'PASS=%d WARN=%d FAIL=%d\n' "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 2
fi
