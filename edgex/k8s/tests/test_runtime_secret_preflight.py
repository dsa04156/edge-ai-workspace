from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

import pytest


K8S_DIR = Path(__file__).resolve().parents[1]
PREFLIGHT = K8S_DIR / "scripts/preflight-runtime-secrets.sh"
FAKE_SECRET_PAYLOAD = "ZmFrZS1zZWNyZXQtcGF5bG9hZA=="
SAFE_IDENTIFIER = re.compile(r"edgex-(?:system|edge)(?:/[a-z0-9.-]+){0,2}")

REQUIRED_NAMESPACES = ("edgex-system", "edgex-edge")
REQUIRED_SECRETS = (
    ("edgex-system", "edgex-postgres-credentials", ("username", "password")),
    ("edgex-system", "edgex-telemetry-plane-credentials", ("database-url",)),
    ("edgex-system", "edgex-telemetry-edge-auth", ("edge-auth-secrets.json",)),
    ("edgex-system", "edgex-ingest-gateway-tls", ("ca.crt", "tls.crt", "tls.key")),
    (
        "edgex-edge",
        "edgex-edge-agent-sensehat-credentials",
        ("edge-auth-secret",),
    ),
    (
        "edgex-edge",
        "edgex-edge-agent-sensehat-gateway-mtls",
        ("ca.crt", "tls.crt", "tls.key"),
    ),
)
SECRET_IDENTIFIERS = tuple(
    f"{namespace}/{secret}" for namespace, secret, _ in REQUIRED_SECRETS
)
KEY_IDENTIFIERS = tuple(
    f"{namespace}/{secret}/{key}"
    for namespace, secret, keys in REQUIRED_SECRETS
    for key in keys
)
EXPECTED_LOOKUPS = tuple(
    identifier
    for namespace in REQUIRED_NAMESPACES
    for identifier in (
        namespace,
        *(
            lookup
            for secret_namespace, secret, keys in REQUIRED_SECRETS
            if secret_namespace == namespace
            for lookup in (
                f"{secret_namespace}/{secret}",
                *(f"{secret_namespace}/{secret}/{key}" for key in keys),
            )
        ),
    )
)


FAKE_KUBECTL = """#!/bin/sh
set -eu

log=${PREFLIGHT_LOOKUP_LOG:?}
failure_kind=${PREFLIGHT_FAILURE_KIND:-}
failure_identifier=${PREFLIGHT_FAILURE_IDENTIFIER:-}

record_lookup() {
    printf '%s\\n' "$1" >> "$log"
}

if [ "$1" = "get" ] && [ "$2" = "namespace" ]; then
    namespace=$3
    record_lookup "$namespace"
    if [ "$failure_kind" = "namespace" ] \
        && [ "$failure_identifier" = "$namespace" ]; then
        exit 1
    fi
    exit 0
fi

namespace=$2
secret=$5
secret_identifier=$namespace/$secret
if [ "$#" -eq 5 ]; then
    record_lookup "$secret_identifier"
    if [ "$failure_kind" = "secret" ] \
        && [ "$failure_identifier" = "$secret_identifier" ]; then
        exit 1
    fi
    exit 0
fi

template=$7
IFS='"'
set -- $template
key=$2
key_identifier=$secret_identifier/$key
record_lookup "$key_identifier"

if [ "$failure_identifier" = "$key_identifier" ]; then
    case "$failure_kind" in
        missing-key|empty-value)
            exit 0
            ;;
        lookup-failure)
            exit 1
            ;;
        lookup-failure-with-payload)
            printf '%s' 'ZmFrZS1zZWNyZXQtcGF5bG9hZA=='
            exit 1
            ;;
    esac
fi

printf '%s' 'ZmFrZS1zZWNyZXQtcGF5bG9hZA=='
"""


def _run_preflight(
    tmp_path: Path,
    *,
    failure_kind: str | None = None,
    failure_identifier: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    kubectl = tmp_path / "kubectl"
    log = tmp_path / "kubectl-lookups"
    kubectl.write_text(FAKE_KUBECTL)
    kubectl.chmod(0o755)

    result = subprocess.run(
        [str(PREFLIGHT)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "KUBECTL": str(kubectl),
            "PREFLIGHT_LOOKUP_LOG": str(log),
            "PREFLIGHT_FAILURE_KIND": failure_kind or "",
            "PREFLIGHT_FAILURE_IDENTIFIER": failure_identifier or "",
        },
    )
    return result, log.read_text().splitlines()


def _assert_safe_failure(
    result: subprocess.CompletedProcess[str], expected_identifier: str
) -> None:
    assert result.returncode != 0
    assert result.stdout == f"{expected_identifier}\n"
    assert result.stderr == ""
    assert SAFE_IDENTIFIER.fullmatch(expected_identifier)
    assert FAKE_SECRET_PAYLOAD not in result.stdout + result.stderr


def test_runtime_secret_preflight_looks_up_exact_complete_inventory(
    tmp_path: Path,
) -> None:
    result, lookups = _run_preflight(tmp_path)

    assert result.returncode == 0
    assert result.stdout == "Runtime Secret preflight passed.\n"
    assert result.stderr == ""
    assert tuple(lookups) == EXPECTED_LOOKUPS
    assert FAKE_SECRET_PAYLOAD not in result.stdout + result.stderr


@pytest.mark.parametrize("namespace", REQUIRED_NAMESPACES)
def test_runtime_secret_preflight_fails_closed_for_each_missing_namespace(
    tmp_path: Path, namespace: str
) -> None:
    result, _ = _run_preflight(
        tmp_path,
        failure_kind="namespace",
        failure_identifier=namespace,
    )

    _assert_safe_failure(result, namespace)


@pytest.mark.parametrize("secret_identifier", SECRET_IDENTIFIERS)
def test_runtime_secret_preflight_fails_closed_for_each_missing_secret(
    tmp_path: Path, secret_identifier: str
) -> None:
    result, _ = _run_preflight(
        tmp_path,
        failure_kind="secret",
        failure_identifier=secret_identifier,
    )

    _assert_safe_failure(result, secret_identifier)


@pytest.mark.parametrize("key_identifier", KEY_IDENTIFIERS)
@pytest.mark.parametrize(
    "failure_kind",
    ("missing-key", "empty-value", "lookup-failure", "lookup-failure-with-payload"),
)
def test_runtime_secret_preflight_fails_closed_for_each_invalid_key(
    tmp_path: Path, key_identifier: str, failure_kind: str
) -> None:
    result, _ = _run_preflight(
        tmp_path,
        failure_kind=failure_kind,
        failure_identifier=key_identifier,
    )

    _assert_safe_failure(result, key_identifier)
