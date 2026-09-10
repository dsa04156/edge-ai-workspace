#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo "usage: bash build-images.sh <crane-executable> <unique-tag>" >&2
  exit 2
fi
crane=$1
tag=$2
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source_dir=$(cd "${script_dir}/.." && pwd)
build_dir=$(mktemp -d)
trap 'rm -rf "${build_dir}"' EXIT
registry=192.168.0.56:5000
operator_base=${registry}/state-aggregator@sha256:f0b59fe7e6769544f49007b4f9ef8cf096115f82810195959004cb1d92ce0ecd
demo_base=docker.io/library/python@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
mkdir -p "${build_dir}/operator/opt/runtime/runtime_operator" "${build_dir}/demo/opt/demo"
cp "${source_dir}"/runtime_operator/*.py "${build_dir}/operator/opt/runtime/runtime_operator/"
cp "${source_dir}/demo/server.py" "${build_dir}/demo/opt/demo/"
tar --sort=name --mtime='UTC 2026-09-10' --numeric-owner --owner=0 --group=0 -C "${build_dir}/operator" -cf "${build_dir}/operator.tar" .
tar --sort=name --mtime='UTC 2026-09-10' --numeric-owner --owner=0 --group=0 -C "${build_dir}/demo" -cf "${build_dir}/demo.tar" .
"${crane}" mutate "${operator_base}" --platform linux/amd64 --set-platform linux/amd64 \
  --append "${build_dir}/operator.tar" --workdir /opt/runtime --user 65532:65532 \
  --entrypoint python,-m,uvicorn --cmd runtime_operator.api:app,--host,0.0.0.0,--port,8080,--workers,1,--timeout-graceful-shutdown,310 \
  --tag "${registry}/runtime-operator:${tag}" --insecure
for arch in amd64 arm64; do
  "${crane}" mutate "${demo_base}" --platform "linux/${arch}" --set-platform "linux/${arch}" \
    --append "${build_dir}/demo.tar" --workdir /opt/demo --user 65532:65532 \
    --entrypoint python --cmd /opt/demo/server.py \
    --tag "${registry}/runtime-contract-demo:${tag}-${arch}" --insecure
done
for image in "runtime-operator:${tag}" "runtime-contract-demo:${tag}-amd64" "runtime-contract-demo:${tag}-arm64"; do
  "${crane}" digest "${registry}/${image}" --insecure
done
