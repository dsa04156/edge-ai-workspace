#!/bin/sh
set -eu

KUBECTL=${KUBECTL:-kubectl}
failed=0

check_namespace() {
    namespace=$1

    if ! "$KUBECTL" get namespace "$namespace" >/dev/null 2>&1; then
        printf '%s\n' "$namespace"
        return 1
    fi
}

check_secret() {
    namespace=$1
    secret=$2
    shift 2

    if ! "$KUBECTL" -n "$namespace" get secret "$secret" >/dev/null 2>&1; then
        printf '%s/%s\n' "$namespace" "$secret"
        failed=1
        return
    fi

    for key in "$@"; do
        if value=$("$KUBECTL" -n "$namespace" get secret "$secret" \
            -o "go-template={{ with index .data \"$key\" }}{{ . }}{{ end }}" 2>/dev/null); then
            if [ -z "$value" ]; then
                printf '%s/%s/%s\n' "$namespace" "$secret" "$key"
                failed=1
            fi
        else
            printf '%s/%s/%s\n' "$namespace" "$secret" "$key"
            failed=1
        fi
    done
}

if check_namespace edgex-system; then
    check_secret edgex-system edgex-postgres-credentials username password
    check_secret edgex-system edgex-telemetry-plane-credentials database-url
    check_secret edgex-system edgex-telemetry-edge-auth edge-auth-secrets.json
    check_secret edgex-system edgex-ingest-gateway-tls ca.crt tls.crt tls.key
else
    failed=1
fi

if check_namespace edgex-edge; then
    check_secret edgex-edge edgex-edge-agent-sensehat-credentials edge-auth-secret
    check_secret edgex-edge edgex-edge-agent-sensehat-gateway-mtls ca.crt tls.crt tls.key
    check_secret edgex-edge edgex-edge-agent-jetson-credentials edge-auth-secret
    check_secret edgex-edge edgex-edge-agent-jetson-gateway-mtls ca.crt tls.crt tls.key
else
    failed=1
fi

if [ "$failed" -ne 0 ]; then
    exit 1
fi

printf '%s\n' 'Runtime Secret preflight passed.'
