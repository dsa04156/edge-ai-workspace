#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8000}"

section() {
  printf '\n== %s ==\n' "$1"
}

run_readonly() {
  printf '\n$ %s\n' "$*"
  "$@" || true
}

section "Repository"
printf 'root=%s\n' "$ROOT_DIR"
printf 'base_url=%s\n' "$BASE_URL"

section "1. Kubernetes nodes"
run_readonly kubectl get nodes -o wide

section "2. Recovery control plane"
run_readonly kubectl -n argocd get application edgex-telemetry \
  -o jsonpath='{.spec.syncPolicy.automated.selfHeal}{"\t"}{.status.sync.status}{"\t"}{.status.health.status}{"\t"}{.status.operationState.phase}{"\n"}'
run_readonly kubectl -n edgex-system get deployment,pod \
  -l app.kubernetes.io/name=edgex-messagebus -o wide
run_readonly kubectl -n kubeedge get daemonset edgemesh-agent -o wide

section "3. EdgeX Device Service workloads"
run_readonly kubectl -n edgex-edge get pods \
  -l app.kubernetes.io/name=device-serial-jetson -o wide
run_readonly kubectl -n edgex-edge get pods \
  -l app.kubernetes.io/name=device-sensehat-raspi -o wide

section "4. EdgeX virtual Device inventory"
run_readonly kubectl get --raw /api/v1/namespaces/edgex-system/services/http:edgex-core-metadata:59881/proxy/api/v3/device/all

section "5. Edge-local ring cache stats"
run_readonly kubectl get --raw /api/v1/namespaces/edgex-edge/services/http:device-serial-jetson:59910/proxy/api/v3/localdata/stats
run_readonly kubectl get --raw /api/v1/namespaces/edgex-edge/services/http:device-sensehat-raspi:59911/proxy/api/v3/localdata/stats

section "6. Core Data persistence readback"
run_readonly kubectl get --raw '/api/v1/namespaces/edgex-system/services/http:edgex-core-data:59880/proxy/api/v3/event/device/name/virtual-temperature-001?limit=1'
run_readonly kubectl get --raw '/api/v1/namespaces/edgex-system/services/http:edgex-core-data:59880/proxy/api/v3/event/device/name/env-sensehat-humidity-01?limit=1'

section "7. State-aggregator API reachability"
for path in /state/nodes /state/devices /state/dashboard /state/summary /state/operator-assistant; do
  printf '\n$ curl -fsS %s%s\n' "$BASE_URL" "$path"
  if curl -fsS --max-time 5 "$BASE_URL$path" >/tmp/edge-ai-e2e-api.json; then
    python3 - <<'PY' || true
from pathlib import Path
text = Path('/tmp/edge-ai-e2e-api.json').read_text(errors='replace')
print(text[:500])
print('... bytes=', len(text))
PY
  else
    echo "WARN: API not reachable. Try port-forward: kubectl -n default port-forward svc/state-aggregator 8000:8000"
  fi
done

section "8. Dashboard API field check"
run_readonly python3 "$ROOT_DIR/tools/check_dashboard_api.py" --base-url "$BASE_URL"

section "9. Expected virtual devices"
cat <<'EOF'
virtual-temperature-001
virtual-light-001
virtual-magnetic-001
virtual-acceleration-x-001
virtual-acceleration-y-001
virtual-acceleration-z-001
env-sensehat-temperature-01
env-sensehat-humidity-01
env-sensehat-pressure-01
imu-sensehat-compass-01
imu-sensehat-orientation-01
imu-sensehat-gyroscope-01

The physical source IDs arduino-001 and sensehat-001 are protocol/tag metadata,
not aggregate EdgeX Devices.
EOF

section "10. Persistence and local cache boundary"
cat <<'EOF'
Core Data/PostgreSQL stores Event/Reading history.
Each Device Service keeps a volatile ring cache for 10 minutes and up to
10,000 samples per Device/resource, with a 64 MiB sample-slot budget per service.
The cache is exposed at /api/v3/localdata/stats and is lost on Pod restart.
Same-node clients use these Service FQDNs instead of fixed IP addresses:
- device-serial-jetson.edgex-edge.svc.cluster.local:59910
- device-sensehat-raspi.edgex-edge.svc.cluster.local:59911
No SQLite outbox or offline replay is deployed. A central MessageBus outage
does not stop the ring cache, but unsent Events are not durably replayed.
EOF
