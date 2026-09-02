#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <registry/image:unique-tag>" >&2
  exit 2
fi

target_image=$1
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
service_dir=$(cd "${script_dir}/.." && pwd)
build_dir=$(mktemp -d)
trap 'rm -rf "${build_dir}"' EXIT

crane_version=v0.21.9
crane_archive=go-containerregistry_Linux_x86_64.tar.gz
crane_sha256=5c16d8ddb971cb1d5e6ed8b1e743da8224414eeba2c2762d8f1a61b2f095699e
base_image=python:3.11-slim@sha256:78b39ef14d8e2b4d71f8dc304f1328c37df95fe0ef99477c2ae6bd3d03784553

curl -fsSL \
  -o "${build_dir}/${crane_archive}" \
  "https://github.com/google/go-containerregistry/releases/download/${crane_version}/${crane_archive}"
echo "${crane_sha256}  ${build_dir}/${crane_archive}" | sha256sum -c -
tar -xzf "${build_dir}/${crane_archive}" -C "${build_dir}" crane

rootfs=${build_dir}/rootfs
mkdir -p "${rootfs}/usr/local/lib/python3.11/site-packages" "${rootfs}/app"
python3 -m pip install \
  --disable-pip-version-check \
  --no-compile \
  --target "${rootfs}/usr/local/lib/python3.11/site-packages" \
  --platform manylinux2014_x86_64 \
  --python-version 3.11 \
  --implementation cp \
  --only-binary=:all: \
  -r "${service_dir}/requirements.txt"
cp -a "${service_dir}/app" "${rootfs}/app/app"
find "${rootfs}" -type d -name __pycache__ -prune -exec rm -rf {} +
tar --numeric-owner --owner=0 --group=0 -C "${rootfs}" -cf "${build_dir}/layer.tar" .

"${build_dir}/crane" mutate "${base_image}" \
  --platform linux/amd64 \
  --set-platform linux/amd64 \
  --append "${build_dir}/layer.tar" \
  --workdir /app \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env PYTHONUNBUFFERED=1 \
  --env DATA_DIR=/app/data \
  --env INSTANCE_MAP_PATH=/app/app/config/instance_map.json \
  --env POLL_INTERVAL_SECONDS=15 \
  --env PROMETHEUS_URL=http://prometheus:9090 \
  --exposed-ports 8000 \
  --cmd=python,-m,uvicorn,app.main:app,--host,0.0.0.0,--port,8000 \
  --tag "${target_image}" \
  --insecure

"${build_dir}/crane" digest "${target_image}" --insecure
