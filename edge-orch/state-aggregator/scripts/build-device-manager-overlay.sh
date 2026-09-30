#!/usr/bin/env bash
# Add Device Manager to the verified deployed image without rebuilding overview assets.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "usage: $0 <registry/image:unique-tag>" >&2
  exit 2
fi
target_image=$1
service_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
build_dir=$(mktemp -d)
trap 'rm -rf "${build_dir}"' EXIT
base_image=192.168.0.56:5000/state-aggregator@sha256:6359ca8163aaad7b2c31f77d706cddc10db0a580125c789ed79e86fd2a92d146
curl -fsSL -o "${build_dir}/crane.tar.gz" \
  https://github.com/google/go-containerregistry/releases/download/v0.21.9/go-containerregistry_Linux_x86_64.tar.gz
echo "5c16d8ddb971cb1d5e6ed8b1e743da8224414eeba2c2762d8f1a61b2f095699e  ${build_dir}/crane.tar.gz" | sha256sum -c -
tar -xzf "${build_dir}/crane.tar.gz" -C "${build_dir}" crane
layer_dir=${build_dir}/layer
mkdir -p "${layer_dir}/app/app" "${layer_dir}/usr/local/lib/python3.11/site-packages"
python3 -m pip install --disable-pip-version-check --no-compile \
  --target "${layer_dir}/usr/local/lib/python3.11/site-packages" \
  --platform manylinux2014_x86_64 --python-version 3.11 --implementation cp --only-binary=:all: \
  jsonschema==4.23.0 rfc3339-validator==0.1.4
for file in main.py config.py common_runtime.py device_manager.py profile_spec.py \
  config/profile_spec_v1.json static/nexus/index.html static/nexus/platform.js \
  static/nexus/device-manager.js static/nexus/device-manager.css; do
  mkdir -p "${layer_dir}/app/app/$(dirname "${file}")"
  cp "${service_dir}/app/${file}" "${layer_dir}/app/app/${file}"
done
tar --numeric-owner --owner=0 --group=0 -C "${layer_dir}" -cf "${build_dir}/layer.tar" .
"${build_dir}/crane" mutate "${base_image}" --platform linux/amd64 \
  --append "${build_dir}/layer.tar" --tag "${target_image}" --insecure
"${build_dir}/crane" digest "${target_image}" --insecure
