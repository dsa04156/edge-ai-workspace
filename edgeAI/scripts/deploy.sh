#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/etri/jinuk/edgeAI
NAMESPACE=default

python3 "$ROOT/scripts/generate_devices.py" > "$ROOT/devices.yaml"
kubectl apply -f "$ROOT/models/"
kubectl apply -f "$ROOT/devices.yaml"

while read -r device_name; do
  [[ -n "$device_name" ]] || continue
  kubectl patch --subresource=status device "$device_name" -n "$NAMESPACE" --type merge -p \
    '{"status":{"reportToCloud":false,"reportCycle":60000}}'
done < <(awk '/^kind: Device$/{in_device=1; next} in_device && /^  name: /{print $2; in_device=0}' "$ROOT/devices.yaml")

kubectl get devicemodel,device,devicestatus -n default
