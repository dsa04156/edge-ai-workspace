#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KUBEEDGE_REF="${KUBEEDGE_REF:-v1.23.1}"
SOURCE_DIR="${SOURCE_DIR:-$(mktemp -d -t kubeedge-cloudcore-XXXXXXXX)}"
IMAGE="${IMAGE:-192.168.0.56:5000/cloudcore:v1.23.1-metricsfix.1}"
PATCH_FILE="${SCRIPT_DIR}/patch/cloudcore-v1.23.1-metrics-fix.patch"

if [[ -e "${SOURCE_DIR}/.git" ]]; then
    echo "SOURCE_DIR already contains a git checkout: ${SOURCE_DIR}" >&2
    exit 1
fi

git clone --depth 1 --branch "${KUBEEDGE_REF}" \
    https://github.com/kubeedge/kubeedge.git "${SOURCE_DIR}"
git -C "${SOURCE_DIR}" apply --check "${PATCH_FILE}"
git -C "${SOURCE_DIR}" apply "${PATCH_FILE}"

(
    cd "${SOURCE_DIR}"
    go test ./cloud/pkg/cloudstream -count=1
    docker build --file build/cloud/Dockerfile --tag "${IMAGE}" .
    docker push "${IMAGE}"
)

echo "Built and pushed ${IMAGE}"
echo "Source checkout retained at ${SOURCE_DIR}"
