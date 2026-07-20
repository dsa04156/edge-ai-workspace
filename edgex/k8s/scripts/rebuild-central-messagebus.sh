#!/usr/bin/env bash
set -euo pipefail

script_path_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_path="$(cd -- "${script_path_dir}/../../.." && pwd)"
cd "${repo_path}"

rtk kubectl config current-context
rtk kubectl get nodes -o wide

if [[ "${1:-}" != "--execute" ]]; then
  rtk kubectl kustomize edgex/k8s >/tmp/edgex-central-messagebus.yaml
  rtk kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml
  echo "preflight complete; pass --execute to delete and rebuild namespace telemetry"
  exit 0
fi

rtk kubectl get node etri-ser0002-cgnmsb
rtk kubectl get node etri-dev0001-jetorn
rtk kubectl get node etri-dev0003-raspi5
rtk kubectl kustomize edgex/k8s >/tmp/edgex-central-messagebus.yaml
rtk kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml
rtk kubectl get all,pvc,configmap,secret -n telemetry || true
rtk kubectl delete namespace telemetry --ignore-not-found=true --wait=true --timeout=300s
rtk kubectl apply -k edgex/k8s
rtk kubectl get pods -n telemetry -o wide
