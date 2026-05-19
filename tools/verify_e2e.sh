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

section "2. mqttvirtual mapper pods"
run_readonly sh -c "kubectl get pods -A -o wide | grep -i mqttvirtual"

section "3. Device CR / DeviceStatus"
run_readonly kubectl get devices.devices.kubeedge.io -A
run_readonly kubectl get devicestatuses.devices.kubeedge.io -A
run_readonly kubectl get devices.devices.kubeedge.io -A -o "custom-columns=NS:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName,MODEL:.spec.deviceModelRef.name"

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

section "6. Publisher commands to run on each edge node"
cat <<'EOF'
Jetson node(etri-dev0001-jetorn):
  DEVICE_PLAN=jetson SIMULATION_MODE=stable python3 mappers/script/test_device.py

Raspberry Pi node(etri-dev0002-raspi5):
  DEVICE_PLAN=rpi SIMULATION_MODE=stable python3 mappers/script/test_device.py

Single device example:
  DEVICE_FILTER=rpi-act-device-03 SIMULATION_MODE=stable python3 mappers/script/test_device.py

Check publisher stdout for:
  [PUB] factory/devices/.../telemetry
EOF

section "7. InfluxDB query reminder"
cat <<'EOF'
Read-only example:
  kubectl exec -n telemetry influxdb-0 -- sh -lc 'influx query --org "$DOCKER_INFLUXDB_INIT_ORG" --token "$DOCKER_INFLUXDB_INIT_ADMIN_TOKEN" '\''from(bucket:"device_telemetry") |> range(start:-30m) |> filter(fn:(r)=> r._measurement == "virtual_device_telemetry") |> last() |> keep(columns:["_time","_value","device_id","property"])'\'''

Meaning:
  _start/_stop = Flux query window
  _time = actual telemetry sample timestamp
  telemetry_fresh = device-level latest sample freshness
  act/rpi-act liveness property = health, not ts
EOF
