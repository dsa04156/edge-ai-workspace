#!/bin/sh
set -eu

KUBECTL=${KUBECTL:-kubectl}
OPENSSL=${OPENSSL:-openssl}
mode=create

case "${1:-}" in
    "") ;;
    --replace) mode=replace ;;
    *)
        printf '%s\n' "usage: $0 [--replace]" >&2
        exit 64
        ;;
esac

command -v "$KUBECTL" >/dev/null 2>&1 || {
    printf '%s\n' "kubectl executable not found: $KUBECTL" >&2
    exit 69
}
command -v "$OPENSSL" >/dev/null 2>&1 || {
    printf '%s\n' "openssl executable not found: $OPENSSL" >&2
    exit 69
}

if [ "$mode" = create ]; then
    for namespace in default edgex-edge; do
        if "$KUBECTL" -n "$namespace" get secret \
            edgex-adapter-management-auth >/dev/null 2>&1; then
            printf '%s\n' \
                "refusing to rotate existing Secret $namespace/edgex-adapter-management-auth; pass --replace explicitly" \
                >&2
            exit 73
        fi
    done
fi

umask 077
secret_tmp=$(mktemp -d)
cleanup() {
    rm -rf -- "$secret_tmp"
}
trap cleanup EXIT HUP INT TERM

random_hex() {
    "$OPENSSL" rand -hex 32 | tr -d '\r\n'
}

random_hex >"$secret_tmp/internal-hmac-key"
random_hex >"$secret_tmp/management-hmac-key"

for key in internal-hmac-key management-hmac-key; do
    value=$(cat "$secret_tmp/$key")
    case "$value" in
        *[!0-9a-f]*|'')
            printf '%s\n' "generated Secret value is not lowercase hexadecimal: $key" >&2
            exit 70
            ;;
    esac
    if [ "${#value}" -ne 64 ]; then
        printf '%s\n' "generated Secret value has the wrong length: $key" >&2
        exit 70
    fi
    unset value
done

apply_secret() {
    namespace=$1
    name=$2
    shift 2
    manifest="$secret_tmp/$namespace-$name.yaml"
    "$KUBECTL" -n "$namespace" create secret generic "$name" "$@" \
        --dry-run=client -o yaml >"$manifest"
    "$KUBECTL" apply -f "$manifest" >/dev/null
    rm -f -- "$manifest"
    printf '%s\n' "provisioned $namespace/$name"
}

apply_secret default edgex-adapter-management-auth \
    "--from-file=internal-hmac-key=$secret_tmp/internal-hmac-key" \
    "--from-file=management-hmac-key=$secret_tmp/management-hmac-key"
apply_secret edgex-edge edgex-adapter-management-auth \
    "--from-file=internal-hmac-key=$secret_tmp/internal-hmac-key"

KUBECTL="$KUBECTL" "$(dirname "$0")/preflight-adapter-management-secrets.sh"
