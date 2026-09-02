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
base_image=python:3.11-slim@sha256:20eadabc42589e6543b24a64ab305b9895e9fcf6dbb2cadb14812f394ecdbadf

curl -fsSL \
  -o "${build_dir}/${crane_archive}" \
  "https://github.com/google/go-containerregistry/releases/download/${crane_version}/${crane_archive}"
echo "${crane_sha256}  ${build_dir}/${crane_archive}" | sha256sum -c -
tar -xzf "${build_dir}/${crane_archive}" -C "${build_dir}" crane

base_architecture=$("${build_dir}/crane" config "${base_image}" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["architecture"])')
if [[ "${base_architecture}" != arm64 ]]; then
  echo "refusing to build ARM64 image from ${base_architecture} base manifest" >&2
  exit 1
fi

rootfs=${build_dir}/rootfs
mkdir -p "${rootfs}/usr/local/lib/python3.11/site-packages" "${rootfs}/app"
python3 -m pip install \
  --disable-pip-version-check \
  --no-compile \
  --target "${rootfs}/usr/local/lib/python3.11/site-packages" \
  --platform manylinux2014_aarch64 \
  --python-version 3.11 \
  --implementation cp \
  --only-binary=:all: \
  -r "${service_dir}/requirements.txt"
cp -a "${service_dir}/app" "${rootfs}/app/app"
find "${rootfs}" -type d -name __pycache__ -prune -exec rm -rf {} +
tar --numeric-owner --owner=0 --group=0 -C "${rootfs}" -cf "${build_dir}/layer.tar" .

"${build_dir}/crane" mutate "${base_image}" \
  --platform linux/arm64 \
  --set-platform linux/arm64 \
  --append "${build_dir}/layer.tar" \
  --user 65532:65532 \
  --workdir /app \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env PYTHONUNBUFFERED=1 \
  --exposed-ports 8080 \
  --cmd=python,-m,uvicorn,app.main:app,--host,0.0.0.0,--port,8080 \
  --tag "${target_image}" \
  --insecure

"${build_dir}/crane" digest "${target_image}" --insecure
