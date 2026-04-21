#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BIN_DIR="${SCRIPT_DIR}/bin"
BIN_PATH="${BIN_DIR}/mqttvirtual"
CONFIG_FILE="${CONFIG_FILE:-${SCRIPT_DIR}/config.yaml}"
KLOG_V="${KLOG_V:-4}"
RUN_ARGS="--config-file ${CONFIG_FILE} --v ${KLOG_V}"
LOG_FILE="${LOG_FILE:-${SCRIPT_DIR}/mapper.log}"
SOCK_PATH="${SOCK_PATH:-/etc/kubeedge/mqttvirtual.sock}"
DMI_SOCK="${DMI_SOCK:-/etc/kubeedge/dmi.sock}"
TARGET_ARCH="${TARGET_ARCH:-}"

# Try common locations first, then fall back to legacy sibling layout.
API_DIR="${API_DIR:-${SCRIPT_DIR}/../../api}"
FRAMEWORK_DIR="${FRAMEWORK_DIR:-${SCRIPT_DIR}/../../mapper-framework}"
if [[ ! -d "${API_DIR}" || ! -d "${FRAMEWORK_DIR}" ]]; then
  API_DIR="${API_DIR_FALLBACK:-${SCRIPT_DIR}/../api}"
  FRAMEWORK_DIR="${FRAMEWORK_DIR_FALLBACK:-${SCRIPT_DIR}/../mapper-framework}"
fi

is_valid_module_dir() {
  local dir="$1"
  local module_name="$2"

  [[ -d "${dir}" ]] || return 1
  [[ -f "${dir}/go.mod" ]] || return 1
  grep -q "^module ${module_name}$" "${dir}/go.mod"
}

pick_module_dir() {
  local module_name="$1"
  shift
  local candidates=("$@")
  local d
  for d in "${candidates[@]}"; do
    if is_valid_module_dir "${d}" "${module_name}"; then
      echo "${d}"
      return 0
    fi
  done
  return 1
}

resolve_module_dirs() {
  if [[ -z "${API_DIR:-}" ]]; then
    API_DIR=""
  fi
  if [[ -z "${FRAMEWORK_DIR:-}" ]]; then
    FRAMEWORK_DIR=""
  fi

  if ! is_valid_module_dir "${API_DIR}" "github.com/kubeedge/api"; then
    API_DIR="$(pick_module_dir "github.com/kubeedge/api" \
      "${SCRIPT_DIR}/../api" \
      "${SCRIPT_DIR}/../../api" \
      "${SCRIPT_DIR}/../../../api" \
      "${SCRIPT_DIR}/../../../../api" \
    )" || API_DIR=""
  fi

  if ! is_valid_module_dir "${FRAMEWORK_DIR}" "github.com/kubeedge/mapper-framework"; then
    FRAMEWORK_DIR="$(pick_module_dir "github.com/kubeedge/mapper-framework" \
      "${SCRIPT_DIR}/../mapper-framework" \
      "${SCRIPT_DIR}/../../mapper-framework" \
      "${SCRIPT_DIR}/../../../mapper-framework" \
      "${SCRIPT_DIR}/../../../../mapper-framework" \
    )" || FRAMEWORK_DIR=""
  fi
}

usage() {
  cat <<'EOF'
Usage:
  ./register_mapper_rpi.sh <command>

Commands:
  check     Validate environment and dependency paths
  build     Build mqttvirtual mapper binary
  start     Start mapper (registers to edgecore on startup)
  run-fg    Run mapper in foreground (tee log), like manual command
  stop      Stop mapper process and clean mapper socket
  restart   stop + start
  status    Show process/socket/log tail

Optional env vars:
  API_DIR, FRAMEWORK_DIR   Override replace target paths in go.mod
  LOG_FILE                 Mapper log path (default: ./mapper.log)
  CONFIG_FILE              Mapper config file path (default: ./config.yaml)
  KLOG_V                   Mapper klog verbosity (default: 4)
  TARGET_ARCH              Build target arch (auto: arm64/amd64/arm)
  LOCAL_BIN_PATH           Local quick-run binary path (default: ./mqttvirtual-<arch>)
  SOCK_PATH                Mapper sock path (default: /etc/kubeedge/mqttvirtual.sock)
  DMI_SOCK                 Edgecore DMI sock path (default: /etc/kubeedge/dmi.sock)
EOF
}

detect_target_arch() {
  if [[ -n "${TARGET_ARCH}" ]]; then
    return
  fi

  case "$(uname -m)" in
    aarch64)
      TARGET_ARCH="arm64"
      ;;
    armv7l|armv6l)
      TARGET_ARCH="arm"
      ;;
    x86_64)
      TARGET_ARCH="amd64"
      ;;
    *)
      echo "[ERROR] Unsupported host arch: $(uname -m). Set TARGET_ARCH manually." >&2
      exit 1
      ;;
  esac
}

set_local_bin_path() {
  LOCAL_BIN_PATH="${LOCAL_BIN_PATH:-${SCRIPT_DIR}/mqttvirtual-${TARGET_ARCH}}"
}

need_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[ERROR] Missing command: ${cmd}" >&2
    exit 1
  fi
}

check_env() {
  detect_target_arch
  set_local_bin_path
  resolve_module_dirs

  need_cmd go
  need_cmd sed

  if [[ ! -S "${DMI_SOCK}" ]]; then
    echo "[WARN] DMI socket not found: ${DMI_SOCK}" >&2
    echo "       edgecore is not ready, mapper register may fail." >&2
  else
    echo "[OK] DMI socket: ${DMI_SOCK}"
  fi

  if [[ ! -f "${SCRIPT_DIR}/go.mod" ]]; then
    echo "[ERROR] go.mod not found in mapper folder: ${SCRIPT_DIR}" >&2
    exit 1
  fi

  if [[ ! -d "${API_DIR}" ]]; then
    echo "[ERROR] API dir not found: ${API_DIR}" >&2
    echo "       Set API_DIR to your api repo path (contains go.mod: module github.com/kubeedge/api)." >&2
    exit 1
  fi

  if [[ ! -d "${FRAMEWORK_DIR}" ]]; then
    echo "[ERROR] mapper-framework dir not found: ${FRAMEWORK_DIR}" >&2
    echo "       Set FRAMEWORK_DIR to your mapper-framework repo path (contains go.mod: module github.com/kubeedge/mapper-framework)." >&2
    exit 1
  fi

  echo "[OK] API_DIR=${API_DIR}"
  echo "[OK] FRAMEWORK_DIR=${FRAMEWORK_DIR}"
  echo "[OK] TARGET_ARCH=${TARGET_ARCH}"
}

build_mapper() {
  check_env
  mkdir -p "${BIN_DIR}"

  local tmp_mod
  tmp_mod="$(mktemp)"
  cp "${SCRIPT_DIR}/go.mod" "${tmp_mod}"
  trap "cp '${tmp_mod}' '${SCRIPT_DIR}/go.mod'; rm -f '${tmp_mod}'; trap - RETURN" RETURN

  sed -i "s#github.com/kubeedge/api => .*#github.com/kubeedge/api => ${API_DIR}#" "${SCRIPT_DIR}/go.mod"
  sed -i "s#github.com/kubeedge/mapper-framework => .*#github.com/kubeedge/mapper-framework => ${FRAMEWORK_DIR}#" "${SCRIPT_DIR}/go.mod"

  echo "[INFO] Building mapper binary..."
  (cd "${SCRIPT_DIR}" && CGO_ENABLED=0 GOOS=linux GOARCH="${TARGET_ARCH}" go build -o "${BIN_PATH}" ./cmd/main.go)
  (cd "${SCRIPT_DIR}" && CGO_ENABLED=0 GOOS=linux GOARCH="${TARGET_ARCH}" go build -o "${LOCAL_BIN_PATH}" ./cmd)
  echo "[OK] Build done: ${BIN_PATH}"
  echo "[OK] Local run binary: ${LOCAL_BIN_PATH}"
}

stop_mapper() {
  local stop_pattern
  stop_pattern="$(basename "${LOCAL_BIN_PATH}") --config-file ${CONFIG_FILE}"

  pkill -f "${stop_pattern}" || true
  if pgrep -af "${BIN_PATH}" >/dev/null 2>&1; then
    echo "[INFO] Stopping mapper process..."
    pkill -f "${BIN_PATH}" || true
  else
    echo "[INFO] No running mapper process found"
  fi

  if [[ -e "${SOCK_PATH}" ]]; then
    echo "[INFO] Removing stale socket: ${SOCK_PATH}"
    sudo rm -f "${SOCK_PATH}"
  fi
}

start_mapper() {
  if [[ ! -x "${BIN_PATH}" ]]; then
    echo "[WARN] Binary not found, running build first"
    build_mapper
  fi

  if [[ ! -S "${DMI_SOCK}" ]]; then
    echo "[ERROR] DMI socket missing: ${DMI_SOCK}" >&2
    echo "       Start edgecore first, then retry." >&2
    exit 1
  fi

  stop_mapper

  echo "[INFO] Starting mapper..."
  nohup "${BIN_PATH}" ${RUN_ARGS} >"${LOG_FILE}" 2>&1 &
  sleep 1

  if pgrep -af "${BIN_PATH}" >/dev/null 2>&1; then
    echo "[OK] Mapper started"
    pgrep -af "${BIN_PATH}" | head -n 1
  else
    echo "[ERROR] Mapper failed to start. Check log: ${LOG_FILE}" >&2
    tail -n 40 "${LOG_FILE}" || true
    exit 1
  fi
}

run_fg_mapper() {
  check_env

  if [[ ! -x "${LOCAL_BIN_PATH}" ]]; then
    echo "[WARN] Local binary not found, running build first"
    build_mapper
  fi

  if [[ ! -S "${DMI_SOCK}" ]]; then
    echo "[ERROR] DMI socket missing: ${DMI_SOCK}" >&2
    echo "       Start edgecore first, then retry." >&2
    exit 1
  fi

  stop_mapper

  echo "[INFO] Running foreground mapper with tee log"
  echo "[INFO] Command: sudo ${LOCAL_BIN_PATH} ${RUN_ARGS} 2>&1 | tee ${LOG_FILE}"
  sudo "${LOCAL_BIN_PATH}" ${RUN_ARGS} 2>&1 | tee "${LOG_FILE}"
}

status_mapper() {
  echo "== process =="
  pgrep -af "${BIN_PATH}" || true

  echo "== sockets =="
  ls -l "${SOCK_PATH}" "${DMI_SOCK}" 2>/dev/null || true

  echo "== last logs =="
  tail -n 30 "${LOG_FILE}" 2>/dev/null || echo "(no log file yet)"
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    check)
      check_env
      ;;
    build)
      build_mapper
      ;;
    start)
      start_mapper
      ;;
    run-fg)
      run_fg_mapper
      ;;
    stop)
      stop_mapper
      ;;
    restart|register)
      stop_mapper
      start_mapper
      ;;
    status)
      status_mapper
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "${1:-}"
