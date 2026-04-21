cd() {
  builtin cd "$@" && ls
}

alias ..='cd ..'           # 상위 디렉토리로 이동
alias ...='cd ../..'       # 두 단계 상위 디렉토리로 이동
alias h='history'          # 최근 명령어 조회
alias c='clear'  #         # 터미널 로그 지우기
# k8s
alias k='kubectl'
alias kg='kubectl get'
alias kga='kubectl get all'
alias kd='kubectl describe'
alias kf='kubectl apply -f'      # YAML 파일을 사용하여 리소스 적용
alias kx='kubectl exec -it'       # 파드에서 명령어 실행
alias kr='kubectl rollout'        # 배포 롤아웃 관리
alias ks='kubectl get services'   # 서비스 목록 조회
alias ksc='kubectl get configmaps' # ConfigMap 목록 조회
alias kgpa='kubectl get pod --all-namespaces'
alias kgp='kubectl get pod'
alias kd='kubectl describe'
alias kdel='kubectl delete'
alias kcg='kubectl config get-contexts'
alias kcu='kubectl config use-context'

# ---- kedge helpers ----
# profile -> labelKey, taintKey, taintVal, effect
declare -A KEDGE_LABEL_KEY=(
  [edge]="node-role.kubernetes.io/edge"
  [cloud]="node-role.kubernetes.io/control-plane"
  [gpu]="nvidia.com/gpu.present"
)
declare -A KEDGE_TAINT_KEY=(
  [edge]="dedicated"
  [cloud]="dedicated"
  [gpu]="dedicated"
)
declare -A KEDGE_TAINT_VAL=(
  [edge]="edge"
  [cloud]="cloud"
  [gpu]="gpu"
)
declare -A KEDGE_TAINT_EFFECT=(
  [edge]="NoSchedule"
  [cloud]="NoSchedule"
  [gpu]="NoSchedule"
)

_kedge_profile_or_die() {
  local p="$1"
  [[ -n "${KEDGE_LABEL_KEY[$p]:-}" ]] || {
    echo "unknown profile: $p (known: ${!KEDGE_LABEL_KEY[@]})" >&2
    return 2
  }
}

# kl <node> <profile>
kl() {
  local node="${1:-}" prof="${2:-}"
  [[ -n "$node" && -n "$prof" ]] || { echo "usage: kl <node> <profile>" >&2; return 2; }
  _kedge_profile_or_die "$prof" || return $?
  kubectl label node "$node" "${KEDGE_LABEL_KEY[$prof]}=" --overwrite
}

# kdl <node> <profile>
kdl() {
  local node="${1:-}" prof="${2:-}"
  [[ -n "$node" && -n "$prof" ]] || { echo "usage: kdl <node> <profile>" >&2; return 2; }
  _kedge_profile_or_die "$prof" || return $?
  kubectl label node "$node" "${KEDGE_LABEL_KEY[$prof]}-" >/dev/null
}

# kt <node> <profile>
kt() {
  local node="${1:-}" prof="${2:-}"
  [[ -n "$node" && -n "$prof" ]] || { echo "usage: kt <node> <profile>" >&2; return 2; }
  _kedge_profile_or_die "$prof" || return $?
  kubectl taint node "$node" "${KEDGE_TAINT_KEY[$prof]}=${KEDGE_TAINT_VAL[$prof]}:${KEDGE_TAINT_EFFECT[$prof]}" --overwrite
}

# kut <node> <profile>
kut() {
  local node="${1:-}" prof="${2:-}"
  [[ -n "$node" && -n "$prof" ]] || { echo "usage: kut <node> <profile>" >&2; return 2; }
  _kedge_profile_or_die "$prof" || return $?
  kubectl taint node "$node" "${KEDGE_TAINT_KEY[$prof]}-" >/dev/null || true
}

kpin() {
  local kind="${1:-}" name="${2:-}" prof="${3:-}"; shift 3 || true
  local ns="default"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -n|--namespace) ns="$2"; shift 2;;
      *) shift;;
    esac
  done
  [[ -n "$kind" && -n "$name" && -n "$prof" ]] || { echo "usage: kpin <kind> <name> <profile> -n <ns>" >&2; return 2; }
  _kedge_profile_or_die "$prof" || return $?

  local labelKey="${KEDGE_LABEL_KEY[$prof]}"
  local tkey="${KEDGE_TAINT_KEY[$prof]}"
  local tval="${KEDGE_TAINT_VAL[$prof]}"
  local teff="${KEDGE_TAINT_EFFECT[$prof]}"

  local patch
  patch="$(cat <<EOF
{
  "spec": {
    "template": {
      "spec": {
        "affinity": {
          "nodeAffinity": {
            "requiredDuringSchedulingIgnoredDuringExecution": {
              "nodeSelectorTerms": [
                { "matchExpressions": [ { "key": "${labelKey}", "operator": "Exists" } ] }
              ]
            }
          }
        },
        "tolerations": [
          { "key": "${tkey}", "operator": "Equal", "value": "${tval}", "effect": "${teff}" }
        ]
      }
    }
  }
}
EOF
)"
  kubectl -n "$ns" patch "$kind" "$name" --type='merge' -p "$patch"
}

# kunpin <kind> <name> <profile> -n <ns>
# (안전하게 affinity만 제거. toleration만 골라 제거하려면 jq가 필요함)
kunpin() {
  local kind="${1:-}" name="${2:-}" prof="${3:-}"; shift 3 || true
  local ns="default"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -n|--namespace) ns="$2"; shift 2;;
      *) shift;;
    esac
  done
  [[ -n "$kind" && -n "$name" && -n "$prof" ]] || { echo "usage: kunpin <kind> <name> <profile> -n <ns>" >&2; return 2; }
  _kedge_profile_or_die "$prof" || return $?

  kubectl -n "$ns" patch "$kind" "$name" --type='json' -p '[
    {"op":"remove","path":"/spec/template/spec/affinity"}
  ]' 2>/dev/null || true

  echo "NOTE: affinity removed. If you also want to remove toleration ${KEDGE_TAINT_KEY[$prof]}=${KEDGE_TAINT_VAL[$prof]}, remove it from spec.tolerations."
}
# ---- /kedge helpers ----



