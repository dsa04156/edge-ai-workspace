#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="edgex-system"
RUN_ID="${RUN_ID:-run-$(date -u +%Y%m%dt%H%M%S)-${RANDOM}}"
POD_NAME="edgex-core-data-loadtest-${RUN_ID}"
DEVICES="${DEVICES:-1000}"
PER_DEVICE_HZ="${PER_DEVICE_HZ:-0.0166666667}"
DURATION="${DURATION:-60s}"
CONCURRENCY="${CONCURRENCY:-128}"
MAINTENANCE_CONCURRENCY="${MAINTENANCE_CONCURRENCY:-8}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-5s}"
MAX_ERROR_RATE="${MAX_ERROR_RATE:-0}"
MAX_P95="${MAX_P95:-1s}"
MIN_RATE_RATIO="${MIN_RATE_RATIO:-0.95}"
VERIFY="${VERIFY:-true}"
CLEANUP_EVENTS="${CLEANUP_EVENTS:-true}"
KEEP_RESOURCES="${KEEP_RESOURCES:-0}"
CORE_DATA_URL="http://edgex-core-data.edgex-system.svc.cluster.local:59880"
REPORT_DIR="$ROOT_DIR/artifacts/edgex-loadtest"
REPORT_FILE="$REPORT_DIR/${RUN_ID}.json"
LATEST_REPORT="$REPORT_DIR/latest.json"
TEMP_DIR="$(mktemp -d /tmp/edgex-core-data-loadtest.XXXXXX)"
BINARY_PATH="$TEMP_DIR/edgex-core-data-loadtest"
POD_CREATED=0

if [[ ! "$RUN_ID" =~ ^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$ ]]; then
  echo "RUN_ID must be 1-32 lowercase letters, digits, or hyphens" >&2
  exit 2
fi

cleanup() {
  local status=$?
  if [[ "$KEEP_RESOURCES" != "1" && "$POD_CREATED" == "1" ]]; then
    kubectl -n "$NAMESPACE" delete pod "$POD_NAME" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  fi
  case "$TEMP_DIR" in
    /tmp/edgex-core-data-loadtest.*)
      rm -rf -- "$TEMP_DIR"
      ;;
  esac
  return "$status"
}
trap cleanup EXIT INT TERM

mkdir -p "$REPORT_DIR"

(
  cd "$ROOT_DIR/tools/edgex-core-data-loadtest"
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags="-s -w" -o "$BINARY_PATH" .
)

kubectl create -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${POD_NAME}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: edgex-core-data-loadtest
    app.kubernetes.io/part-of: edgex-system
    edge-ai.io/load-test-run: ${RUN_ID}
spec:
  restartPolicy: Never
  terminationGracePeriodSeconds: 1
  automountServiceAccountToken: false
  nodeSelector:
    kubernetes.io/hostname: etri-ser0002-cgnmsb
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
    runAsGroup: 65534
    fsGroup: 65534
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: runner
      image: busybox:1.36.1@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662
      imagePullPolicy: IfNotPresent
      command:
        - /bin/sh
        - -c
        - while true; do sleep 3600; done
      resources:
        requests:
          cpu: 500m
          memory: 64Mi
        limits:
          cpu: "2"
          memory: 512Mi
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: work
          mountPath: /work
  volumes:
    - name: work
      emptyDir: {}
EOF
POD_CREATED=1

kubectl -n "$NAMESPACE" wait --for=condition=Ready "pod/$POD_NAME" --timeout=120s
kubectl cp "$BINARY_PATH" "$NAMESPACE/$POD_NAME:/work/edgex-core-data-loadtest" -c runner
kubectl -n "$NAMESPACE" exec "$POD_NAME" -c runner -- test -x /work/edgex-core-data-loadtest

set +e
OUTPUT="$(
  kubectl -n "$NAMESPACE" exec "$POD_NAME" -c runner -- \
    /work/edgex-core-data-loadtest \
      --base-url="$CORE_DATA_URL" \
      --run-id="$RUN_ID" \
      --devices="$DEVICES" \
      --per-device-hz="$PER_DEVICE_HZ" \
      --duration="$DURATION" \
      --concurrency="$CONCURRENCY" \
      --maintenance-concurrency="$MAINTENANCE_CONCURRENCY" \
      --request-timeout="$REQUEST_TIMEOUT" \
      --max-error-rate="$MAX_ERROR_RATE" \
      --max-p95="$MAX_P95" \
      --min-rate-ratio="$MIN_RATE_RATIO" \
      --verify="$VERIFY" \
      --cleanup="$CLEANUP_EVENTS"
)"
RUN_STATUS=$?
set -e

printf '%s\n' "$OUTPUT" >"$REPORT_FILE"
cp "$REPORT_FILE" "$LATEST_REPORT"

if ! python3 -m json.tool "$REPORT_FILE" >/dev/null; then
  echo "load-test output is not valid JSON: $REPORT_FILE" >&2
  exit 2
fi

cat "$REPORT_FILE"
exit "$RUN_STATUS"
