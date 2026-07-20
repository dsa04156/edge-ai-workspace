#!/usr/bin/env bash
set -euo pipefail

script_path_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_path="$(cd -- "${script_path_dir}/../../.." && pwd)"
cd "${repo_path}"

rtk kubectl config current-context
rtk kubectl get nodes -o wide

edge_nodes=(
  etri-ser0002-cgnmsb
  etri-dev0001-jetorn
  etri-dev0003-raspi5
)

for node_name in "${edge_nodes[@]}"; do
  rtk kubectl get node "${node_name}"
done

rtk kubectl kustomize edgex/k8s >/tmp/edgex-central-messagebus.yaml
rtk kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml

cluster_dns_ip="$(
  rtk kubectl -n kube-system get service kube-dns \
    -o jsonpath='{.spec.clusterIP}'
)"

for node_name in "${edge_nodes[@]}"; do
  edgemesh_agent="$(
    rtk kubectl -n kubeedge get pod \
      -l kubeedge=edgemesh-agent \
      --field-selector "spec.nodeName=${node_name}" \
      -o jsonpath='{.items[0].metadata.name}'
  )"
  if [[ -z "${edgemesh_agent}" ]]; then
    echo "EdgeMesh agent not found on ${node_name}" >&2
    exit 1
  fi
  rtk kubectl -n kubeedge exec "${edgemesh_agent}" -- \
    nslookup kubernetes.default.svc.cluster.local "${cluster_dns_ip}"
done

if [[ "${1:-}" != "--execute" ]]; then
  echo "preflight complete; pass --execute to replace labeled EdgeX resources"
  exit 0
fi

rtk kubectl get all,pvc,configmap,secret -n telemetry || true
rtk kubectl delete deployment,statefulset,job,service,configmap,secret,pvc \
  -n telemetry \
  -l app.kubernetes.io/part-of=edgex-telemetry \
  --ignore-not-found=true \
  --wait=true \
  --timeout=300s
rtk kubectl apply -k edgex/k8s
rtk kubectl -n telemetry rollout status statefulset/edgex-postgres --timeout=300s
rtk kubectl -n telemetry rollout status deployment/edgex-messagebus --timeout=300s
rtk kubectl -n telemetry rollout status deployment/edgex-core-keeper --timeout=300s
rtk kubectl -n telemetry wait \
  --for=condition=complete \
  job/edgex-core-common-config-bootstrapper \
  --timeout=300s
rtk kubectl -n telemetry rollout status deployment/edgex-core-data --timeout=300s
rtk kubectl -n telemetry rollout status deployment/edgex-core-metadata --timeout=300s
rtk kubectl -n telemetry rollout status deployment/edgex-core-command --timeout=300s
rtk kubectl -n telemetry rollout status deployment/edgex-device-mqtt --timeout=300s
rtk kubectl -n telemetry rollout status deployment/edgex-device-mqtt-sensehat --timeout=300s
rtk kubectl get pods -n telemetry -o wide
