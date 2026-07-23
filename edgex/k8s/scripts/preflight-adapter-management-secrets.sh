#!/bin/sh
set -eu

KUBECTL=${KUBECTL:-kubectl}
failed=0

check_secret() {
    namespace=$1
    name=$2
    shift 2
    if ! "$KUBECTL" -n "$namespace" get secret "$name" >/dev/null 2>&1; then
        printf '%s/%s\n' "$namespace" "$name"
        failed=1
        return
    fi
    for key in "$@"; do
        value=$("$KUBECTL" -n "$namespace" get secret "$name" \
            -o "go-template={{ with index .data \"$key\" }}{{ . }}{{ end }}" \
            2>/dev/null || true)
        if [ -z "$value" ]; then
            printf '%s/%s/%s\n' "$namespace" "$name" "$key"
            failed=1
        fi
    done
}

check_secret default edgex-adapter-management-auth \
    admin-token management-hmac-key internal-hmac-key
check_secret edgex-edge edgex-adapter-management-auth internal-hmac-key

default_internal=$("$KUBECTL" -n default get secret edgex-adapter-management-auth \
    -o 'go-template={{ with index .data "internal-hmac-key" }}{{ . }}{{ end }}' \
    2>/dev/null || true)
edge_internal=$("$KUBECTL" -n edgex-edge get secret edgex-adapter-management-auth \
    -o 'go-template={{ with index .data "internal-hmac-key" }}{{ . }}{{ end }}' \
    2>/dev/null || true)
if [ -n "$default_internal" ] && [ -n "$edge_internal" ] \
    && [ "$default_internal" != "$edge_internal" ]; then
    printf '%s\n' "internal HMAC keys do not match" >&2
    failed=1
fi
unset default_internal edge_internal

if [ "$failed" -ne 0 ]; then
    exit 1
fi

printf '%s\n' "Adapter management Secret preflight passed."
