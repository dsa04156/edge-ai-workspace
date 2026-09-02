#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <registry/image:unique-tag>" >&2
  exit 2
fi

target_image=$1
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "${script_dir}/../.." && pwd)
build_dir=$(mktemp -d)
trap 'rm -rf "${build_dir}"' EXIT

crane_version=v0.21.9
crane_archive=go-containerregistry_Linux_x86_64.tar.gz
crane_sha256=5c16d8ddb971cb1d5e6ed8b1e743da8224414eeba2c2762d8f1a61b2f095699e
base_image=nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

curl -fsSL \
  -o "${build_dir}/${crane_archive}" \
  "https://github.com/google/go-containerregistry/releases/download/${crane_version}/${crane_archive}"
echo "${crane_sha256}  ${build_dir}/${crane_archive}" | sha256sum -c -
tar -xzf "${build_dir}/${crane_archive}" -C "${build_dir}" crane

rootfs=${build_dir}/rootfs
web_root=${rootfs}/usr/share/nginx/html
mkdir -p "${web_root}"
cp -a "${repository_root}/docs/html/." "${web_root}/"
cp -a "${repository_root}/docs/assets" "${web_root}/assets"
tar --numeric-owner --owner=0 --group=0 -C "${rootfs}" -cf "${build_dir}/layer.tar" .

"${build_dir}/crane" mutate "${base_image}" \
  --platform linux/amd64 \
  --set-platform linux/amd64 \
  --append "${build_dir}/layer.tar" \
  --tag "${target_image}" \
  --insecure

"${build_dir}/crane" digest "${target_image}" --insecure
