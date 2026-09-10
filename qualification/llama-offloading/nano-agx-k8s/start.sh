#!/usr/bin/env bash
set -euo pipefail
cd "$(rtk proxy dirname "$0")/.."
# A failed read-only storage/node gate prevents every following mutation.
rtk proxy python3 continuity_preflight.py
continuity_manifest="$(rtk proxy mktemp /tmp/nano-agx-start.XXXXXX.yaml)"
trap 'rtk proxy rm -f "$continuity_manifest"' EXIT
rtk proxy kubectl kustomize nano-agx-k8s --load-restrictor LoadRestrictionsNone > "$continuity_manifest"
rtk proxy kubectl apply -f "$continuity_manifest"
rtk proxy kubectl scale deployment/llama-agx -n llama-continuity-test --replicas=1
