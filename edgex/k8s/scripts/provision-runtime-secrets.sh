#!/bin/sh
set -eu

KUBECTL=${KUBECTL:-kubectl}
OPENSSL=${OPENSSL:-openssl}
mode=create

case "${1:-}" in
    "") ;;
    --replace) mode=replace_all ;;
    --replace-telemetry) mode=replace_telemetry ;;
    *)
        printf '%s\n' "usage: $0 [--replace|--replace-telemetry]" >&2
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

umask 077
secret_tmp=$(mktemp -d)
cleanup() {
    rm -rf -- "$secret_tmp"
}
trap cleanup EXIT HUP INT TERM

ensure_namespace() {
    namespace=$1
    if "$KUBECTL" get namespace "$namespace" >/dev/null 2>&1; then
        return
    fi
    manifest="$secret_tmp/namespace-$namespace.yaml"
    "$KUBECTL" create namespace "$namespace" --dry-run=client -o yaml >"$manifest"
    "$KUBECTL" apply -f "$manifest" >/dev/null
}

required_secrets='edgex-system/edgex-postgres-credentials
edgex-system/edgex-telemetry-plane-credentials
edgex-system/edgex-telemetry-edge-auth
edgex-system/edgex-ingest-gateway-tls
edgex-edge/edgex-edge-agent-sensehat-credentials
edgex-edge/edgex-edge-agent-sensehat-gateway-mtls
edgex-edge/edgex-edge-agent-jetson-credentials
edgex-edge/edgex-edge-agent-jetson-gateway-mtls'

ensure_namespace edgex-system
ensure_namespace edgex-edge

if [ "$mode" = create ]; then
    old_ifs=$IFS
    IFS='/'
    printf '%s\n' "$required_secrets" | while read -r identifier; do
        set -- $identifier
        if "$KUBECTL" -n "$1" get secret "$2" >/dev/null 2>&1; then
            printf '%s\n' "refusing to rotate existing Secret $identifier; pass --replace explicitly" >&2
            exit 73
        fi
    done
    IFS=$old_ifs
fi

random_hex() {
    "$OPENSSL" rand -hex 32 | tr -d '\r\n'
}

if [ "$mode" != replace_telemetry ]; then
    printf '%s' edgex >"$secret_tmp/db-username"
    random_hex >"$secret_tmp/db-password"
    db_password=$(tr -d '\n' <"$secret_tmp/db-password")
    printf 'postgresql://edgex:%s@edgex-postgres.edgex-system.svc:5432/edgex_db' \
        "$db_password" >"$secret_tmp/database-url"
    unset db_password
fi

random_hex >"$secret_tmp/sensehat-auth"
random_hex >"$secret_tmp/jetson-auth"
sensehat_auth=$(tr -d '\n' <"$secret_tmp/sensehat-auth")
jetson_auth=$(tr -d '\n' <"$secret_tmp/jetson-auth")
printf '{"etri-dev0001-jetorn":"%s","etri-dev0003-raspi5":"%s"}' \
    "$jetson_auth" "$sensehat_auth" >"$secret_tmp/edge-auth-secrets.json"
unset jetson_auth sensehat_auth

scalar_files='sensehat-auth jetson-auth edge-auth-secrets.json'
hex_files='sensehat-auth jetson-auth'
if [ "$mode" != replace_telemetry ]; then
    scalar_files="db-username db-password database-url $scalar_files"
    hex_files="db-password $hex_files"
fi

for scalar_file in $scalar_files; do
    if [ "$(wc -l <"$secret_tmp/$scalar_file" | tr -d ' ')" -ne 0 ]; then
        printf '%s\n' "generated Secret value unexpectedly contains a newline: $scalar_file" >&2
        exit 70
    fi
done
for hex_file in $hex_files; do
    hex_value=$(cat "$secret_tmp/$hex_file")
    case "$hex_value" in
        *[!0-9a-f]*|'')
            printf '%s\n' "generated Secret value is not lowercase hexadecimal: $hex_file" >&2
            exit 70
            ;;
    esac
    if [ "${#hex_value}" -ne 64 ]; then
        printf '%s\n' "generated Secret value has the wrong length: $hex_file" >&2
        exit 70
    fi
    unset hex_value
done

"$OPENSSL" req -x509 -newkey rsa:3072 -nodes -sha256 -days 3650 \
    -subj '/CN=edgex-telemetry-runtime-ca' \
    -keyout "$secret_tmp/ca.key" -out "$secret_tmp/ca.crt" >/dev/null 2>&1

printf '%s\n' \
    'basicConstraints=critical,CA:FALSE' \
    'keyUsage=critical,digitalSignature,keyEncipherment' \
    'extendedKeyUsage=serverAuth' \
    'subjectAltName=DNS:edgex-ingest-gateway,DNS:edgex-ingest-gateway.edgex-system,DNS:edgex-ingest-gateway.edgex-system.svc,DNS:edgex-ingest-gateway.edgex-system.svc.cluster.local' \
    >"$secret_tmp/gateway.ext"
"$OPENSSL" req -newkey rsa:3072 -nodes -sha256 \
    -subj '/CN=edgex-ingest-gateway.edgex-system.svc.cluster.local' \
    -keyout "$secret_tmp/gateway.key" -out "$secret_tmp/gateway.csr" >/dev/null 2>&1
"$OPENSSL" x509 -req -sha256 -days 825 \
    -in "$secret_tmp/gateway.csr" -CA "$secret_tmp/ca.crt" -CAkey "$secret_tmp/ca.key" \
    -CAcreateserial -extfile "$secret_tmp/gateway.ext" -out "$secret_tmp/gateway.crt" >/dev/null 2>&1

issue_edge_certificate() {
    edge_id=$1
    prefix=$2
    printf '%s\n' \
        'basicConstraints=critical,CA:FALSE' \
        'keyUsage=critical,digitalSignature,keyEncipherment' \
        'extendedKeyUsage=clientAuth,serverAuth' \
        "subjectAltName=DNS:$edge_id" \
        >"$secret_tmp/$prefix.ext"
    "$OPENSSL" req -newkey rsa:3072 -nodes -sha256 \
        -subj "/CN=$edge_id" \
        -keyout "$secret_tmp/$prefix.key" -out "$secret_tmp/$prefix.csr" >/dev/null 2>&1
    "$OPENSSL" x509 -req -sha256 -days 825 \
        -in "$secret_tmp/$prefix.csr" -CA "$secret_tmp/ca.crt" -CAkey "$secret_tmp/ca.key" \
        -CAcreateserial -extfile "$secret_tmp/$prefix.ext" -out "$secret_tmp/$prefix.crt" >/dev/null 2>&1
}

issue_edge_certificate etri-dev0003-raspi5 sensehat
issue_edge_certificate etri-dev0001-jetorn jetson

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

if [ "$mode" != replace_telemetry ]; then
    apply_secret edgex-system edgex-postgres-credentials \
        "--from-file=username=$secret_tmp/db-username" \
        "--from-file=password=$secret_tmp/db-password"
    apply_secret edgex-system edgex-telemetry-plane-credentials \
        "--from-file=database-url=$secret_tmp/database-url"
fi
apply_secret edgex-system edgex-telemetry-edge-auth \
    "--from-file=edge-auth-secrets.json=$secret_tmp/edge-auth-secrets.json"
apply_secret edgex-system edgex-ingest-gateway-tls \
    "--from-file=ca.crt=$secret_tmp/ca.crt" \
    "--from-file=tls.crt=$secret_tmp/gateway.crt" \
    "--from-file=tls.key=$secret_tmp/gateway.key"

apply_secret edgex-edge edgex-edge-agent-sensehat-credentials \
    "--from-file=edge-auth-secret=$secret_tmp/sensehat-auth"
apply_secret edgex-edge edgex-edge-agent-sensehat-gateway-mtls \
    "--from-file=ca.crt=$secret_tmp/ca.crt" \
    "--from-file=tls.crt=$secret_tmp/sensehat.crt" \
    "--from-file=tls.key=$secret_tmp/sensehat.key"
apply_secret edgex-edge edgex-edge-agent-jetson-credentials \
    "--from-file=edge-auth-secret=$secret_tmp/jetson-auth"
apply_secret edgex-edge edgex-edge-agent-jetson-gateway-mtls \
    "--from-file=ca.crt=$secret_tmp/ca.crt" \
    "--from-file=tls.crt=$secret_tmp/jetson.crt" \
    "--from-file=tls.key=$secret_tmp/jetson.key"

KUBECTL="$KUBECTL" "$(dirname "$0")/preflight-runtime-secrets.sh"
