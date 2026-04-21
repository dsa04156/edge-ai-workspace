#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/etri/jinuk/edgeAI

python3 "$ROOT/scripts/generate_devices.py" > "$ROOT/devices.yaml"
kubectl apply -f "$ROOT/models/"
kubectl apply -f "$ROOT/devices.yaml"

kubectl get devicemodel,device,devicestatus -n default
