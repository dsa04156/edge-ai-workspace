#!/usr/bin/env bash
set -euo pipefail
service_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
preview_data_dir=${DATA_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/edgeai-device-manager-preview}
cd "${service_dir}"
exec env DATA_DIR="${preview_data_dir}" \
  DEVICE_MANAGER_ENABLED=true \
  DEVICE_MANAGER_READ_BASE_URL="${DEVICE_MANAGER_READ_BASE_URL:-http://aggregator.192.168.0.56.sslip.io}" \
  .venv/bin/python -m uvicorn app.device_manager_preview:create_app --factory \
  --host 0.0.0.0 --port "${DEVICE_MANAGER_PORT:-8768}" --lifespan off
