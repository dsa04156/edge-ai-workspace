#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <registry/image:tag>" >&2
  exit 2
fi

target_image=$1
build_dir=$(mktemp -d)
trap 'rm -rf "${build_dir}"' EXIT
base_image=192.168.0.56:5000/sensor-anomaly-demo@sha256:9c0bf78ec255a162101fd4927c7ea1ef94c15aa13b8b38e342e24d98014bd6ba
crane_version=v0.21.9
archive=go-containerregistry_Linux_x86_64.tar.gz

curl -fsSL -o "${build_dir}/${archive}" \
  "https://github.com/google/go-containerregistry/releases/download/${crane_version}/${archive}"
echo "5c16d8ddb971cb1d5e6ed8b1e743da8224414eeba2c2762d8f1a61b2f095699e  ${build_dir}/${archive}" | sha256sum -c -
tar -xzf "${build_dir}/${archive}" -C "${build_dir}" crane

rootfs=${build_dir}/rootfs
mkdir -p "${rootfs}/usr/local/lib/python3.11/site-packages"
python3 -m pip install --disable-pip-version-check --no-compile \
  --target "${rootfs}/usr/local/lib/python3.11/site-packages" \
  --platform manylinux2014_aarch64 --python-version 3.11 \
  --implementation cp --only-binary=:all: numpy==2.2.6
find "${rootfs}" -type d -name __pycache__ -prune -exec rm -rf {} +
tar --numeric-owner --owner=0 --group=0 -C "${rootfs}" -cf "${build_dir}/layer.tar" .

"${build_dir}/crane" mutate "${base_image}" --platform linux/arm64 \
  --set-platform linux/arm64 --append "${build_dir}/layer.tar" \
  --tag "${target_image}" --insecure
"${build_dir}/crane" digest "${target_image}" --insecure
