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

section "2. EdgeX Device Service workload"
run_readonly kubectl -n edgex-edge get pods -l app=device-serial-jetson -o wide

section "3. EdgeX virtual Device inventory"
run_readonly kubectl get --raw /api/v1/namespaces/edgex-system/services/http:edgex-core-metadata:59881/proxy/api/v3/device/all

section "4. State-aggregator API reachability"
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
    echo "WARN: API not reachable. Try port-forward: kubectl -n edge-orch port-forward svc/state-aggregator 8000:80 OR kubectl -n default port-forward svc/state-aggregator 8000:8000"
  fi
done

section "5. Dashboard API field check"
run_readonly python3 "$ROOT_DIR/tools/check_dashboard_api.py" --base-url "$BASE_URL"

section "6. Expected Arduino virtual devices"
cat <<'EOF'
virtual-temperature-001
virtual-light-001
virtual-magnetic-001
virtual-acceleration-x-001
virtual-acceleration-y-001
virtual-acceleration-z-001

The physical wire DeviceID arduino-001 is protocol/tag metadata, not an EdgeX Device.
EOF

section "7. Persistence and local cache boundary"
cat <<'EOF'
Core Data/PostgreSQL stores Event/Reading history.
The Device Service keeps only one volatile latest value per virtual Device/resource.
That latest value is not a recent-window cache and is lost on Pod restart.
No SQLite outbox or separate InfluxDB workload is deployed.
EOF
