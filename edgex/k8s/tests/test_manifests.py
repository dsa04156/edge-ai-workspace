from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml


K8S_DIR = Path(__file__).resolve().parents[1]
SERVER2_OVERLAY = K8S_DIR / "overlays/testbed/server2"
EDGE_NAMESPACE_BASE = K8S_DIR / "base/edge-namespace"
CENTRAL_DEPLOYMENTS = {
    "edgex-core-keeper",
    "edgex-core-metadata",
    "edgex-core-data",
    "edgex-core-command",
    "edgex-messagebus",
    "edgex-ingest-gateway",
}
CENTRAL_STATEFULSETS = {"edgex-postgres"}
CENTRAL_JOBS = {"edgex-core-common-config-bootstrapper"}
RETIRED_EDGE_AGENTS = {
    "edgex-edge-agent-jetson",
    "edgex-edge-agent-sensehat",
}


def test_operational_entrypoint_retires_custom_edge_agents() -> None:
    kustomization = yaml.safe_load((K8S_DIR / "kustomization.yaml").read_text())
    assert kustomization["resources"] == [
        "overlays/testbed/server2",
        "base/edge-namespace",
        "base/device-serial-jetson",
        "base/device-sensehat-raspi",
    ]

    resources = _render(K8S_DIR)
    indexed = _named(resources)
    workload_names = {item["metadata"]["name"] for item in _workloads(resources)}
    assert ("Namespace", "edgex-edge") in indexed
    assert not RETIRED_EDGE_AGENTS & workload_names
    assert not {
        name
        for kind, name in indexed
        if kind == "PersistentVolumeClaim"
        and name.startswith("edgex-edge-agent-")
    }
    assert ("Job", "edgex-metadata-bootstrap") not in indexed
    assert ("ConfigMap", "edgex-metadata-contract") not in indexed


def test_operational_entrypoint_keeps_central_edgex_without_device_mqtt() -> None:
    resources = _render(K8S_DIR)
    indexed = _named(resources)
    workload_names = {item["metadata"]["name"] for item in _workloads(resources)}
    assert ("Namespace", "edgex-system") in indexed
    assert ("Namespace", "edgex-edge") in indexed
    assert CENTRAL_DEPLOYMENTS <= workload_names
    assert not RETIRED_EDGE_AGENTS & workload_names
    assert not {name for name in workload_names if "device-mqtt" in name}


def test_obsolete_single_namespace_mqtt_stack_is_removed() -> None:
    obsolete_paths = [
        "namespace.yaml",
        "postgres.yaml",
        "messagebus.yaml",
        "core.yaml",
        "device-mqtt.yaml",
        "config/arduino-001.yaml",
        "config/etri-sensehat-mqtt.yaml",
        "config/etri-uno-mqtt.yaml",
        "config/sensehat-001.yaml",
    ]

    assert not [path for path in obsolete_paths if (K8S_DIR / path).exists()]


def _is_credential_env(name: str) -> bool:
    return (
        "PASSWORD" in name
        or "CREDENTIAL" in name
        or name.endswith("_SECRET")
        or name.endswith("_TOKEN")
        or name.endswith("_AUTH_SECRETS_JSON")
        or name == "TELEMETRY_DATABASE_URL"
    )


def _render(overlay: Path) -> list[dict[str, Any]]:
    """Render locally; kubectl kustomize does not contact a cluster."""
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(overlay)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [document for document in yaml.safe_load_all(result.stdout) if document]


@pytest.fixture(scope="module")
def server_resources() -> list[dict[str, Any]]:
    return _render(SERVER2_OVERLAY)


@pytest.fixture(scope="module")
def edge_resources() -> list[dict[str, Any]]:
    return _render(EDGE_NAMESPACE_BASE)


def _named(documents: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed = {
        (document["kind"], document["metadata"]["name"]): document
        for document in documents
    }
    assert len(indexed) == len(documents), "rendered resources must not have duplicate kind/name"
    return indexed


def _workloads(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        document
        for document in documents
        if document["kind"] in {"Deployment", "StatefulSet", "Job", "Pod"}
    ]


def _pod_spec(workload: dict[str, Any]) -> dict[str, Any]:
    spec = workload["spec"]
    return spec["template"]["spec"] if "template" in spec else spec


def _containers(pod_spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [*pod_spec.get("initContainers", []), *pod_spec.get("containers", [])]


def _env(container: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in container.get("env", [])}


def _container(workload: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    containers = _pod_spec(workload)["containers"]
    if name is None:
        assert len(containers) == 1
        return containers[0]
    return next(container for container in containers if container["name"] == name)
def _database_config_generators() -> dict[str, dict[str, Any]]:
    resources = _named(
        [
            document
            for document in yaml.safe_load_all(
                (K8S_DIR / "base/server/core.yaml").read_text()
            )
            if document
        ]
    )
    return {
        "core-keeper": next(
            container
            for container in _pod_spec(resources[("Deployment", "edgex-core-keeper")])[
                "initContainers"
            ]
            if container["name"] == "generate-database-config"
        ),
        "core-common-config-bootstrapper": next(
            container
            for container in _pod_spec(
                resources[("Job", "edgex-core-common-config-bootstrapper")]
            )["initContainers"]
            if container["name"] == "generate-database-config"
        ),
    }


def _run_database_config_renderer(
    renderer: dict[str, Any],
    tmp_path: Path,
    template: str,
    username: str,
    password: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    resource_dir = tmp_path / "res"
    generated_dir = tmp_path / "generated"
    resource_dir.mkdir(parents=True)
    generated_dir.mkdir()
    template_path = resource_dir / "configuration.yaml"
    output_path = generated_dir / "configuration.yaml"
    template_path.write_text(template)
    command = list(renderer["command"])
    command[-1] = (
        command[-1]
        .replace("/res/configuration.yaml", str(template_path))
        .replace("/generated", str(generated_dir))
    )
    environment = os.environ.copy()
    environment.update(DB_USERNAME=username, DB_PASSWORD=password)
    return (
        subprocess.run(command, check=False, capture_output=True, text=True, env=environment),
        output_path,
    )


def _volume(pod_spec: dict[str, Any], name: str) -> dict[str, Any]:
    return next(volume for volume in pod_spec.get("volumes", []) if volume["name"] == name)


def _secret_ref(env: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return env[name]["valueFrom"]["secretKeyRef"]


def test_server2_renders_one_central_edgex_data_plane(
    server_resources: list[dict[str, Any]],
) -> None:
    resources = _named(server_resources)
    deployments = {name for kind, name in resources if kind == "Deployment"}
    statefulsets = {name for kind, name in resources if kind == "StatefulSet"}
    jobs = {name for kind, name in resources if kind == "Job"}
    services = {name for kind, name in resources if kind == "Service"}
    assert services == {
        "edgex-core-keeper",
        "edgex-core-metadata",
        "edgex-core-data",
        "edgex-core-command",
        "edgex-messagebus",
        "edgex-postgres",
        "edgex-ingest-gateway",
    }

    assert deployments == CENTRAL_DEPLOYMENTS
    assert statefulsets == CENTRAL_STATEFULSETS
    assert jobs == CENTRAL_JOBS
    assert all(
        resource["kind"] == "Namespace"
        or resource["metadata"].get("namespace") == "edgex-system"
        for resource in server_resources
    )
    for name in CENTRAL_DEPLOYMENTS | CENTRAL_STATEFULSETS | CENTRAL_JOBS:
        resource = resources[("Deployment", name)] if name in CENTRAL_DEPLOYMENTS else (
            resources[("StatefulSet", name)] if name in CENTRAL_STATEFULSETS else resources[("Job", name)]
        )
        assert resource["metadata"]["labels"]["app.kubernetes.io/part-of"] == "edgex-system"
        assert _pod_spec(resource)["nodeSelector"] == {
            "kubernetes.io/hostname": "etri-ser0002-cgnmsb"
        }


def test_edge_namespace_base_contains_no_workloads(
    edge_resources: list[dict[str, Any]],
) -> None:
    resources = _named(edge_resources)
    workload_names = {resource["metadata"]["name"] for resource in _workloads(edge_resources)}

    assert not workload_names
    assert set(resources) == {
        ("Namespace", "edgex-edge"),
        ("NetworkPolicy", "edgex-edge-default-deny"),
    }
    assert ("Namespace", "edgex-edge") in resources
    assert all(
        resource["kind"] == "Namespace"
        or resource["metadata"].get("namespace") == "edgex-edge"
        for resource in edge_resources
    )


def test_central_workloads_do_not_use_host_network_or_host_ports(
    server_resources: list[dict[str, Any]], edge_resources: list[dict[str, Any]]
) -> None:
    for workload in _workloads([*server_resources, *edge_resources]):
        pod = _pod_spec(workload)
        name = workload["metadata"]["name"]
        assert pod.get("hostNetwork", False) is False, name
        for container in _containers(pod):
            assert all("hostPort" not in port for port in container.get("ports", []))


def test_workloads_use_immutable_images_and_hardened_runtime_settings(
    server_resources: list[dict[str, Any]], edge_resources: list[dict[str, Any]]
) -> None:
    for workload in _workloads([*server_resources, *edge_resources]):
        pod = _pod_spec(workload)
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for container in _containers(pod):
            image = container["image"]
            assert "@sha256:" in image and not image.endswith(":latest"), image
            assert container["resources"].get("requests")
            assert container["resources"].get("limits")
            security = container["securityContext"]
            assert security["allowPrivilegeEscalation"] is False
            assert security["capabilities"]["drop"] == ["ALL"]
            is_postgres_volume_init = (
                workload["kind"] == "StatefulSet"
                and workload["metadata"]["name"] == "edgex-postgres"
                and container["name"] == "prepare-postgres-volumes"
            )
            if is_postgres_volume_init:
                assert security["capabilities"] == {
                    "drop": ["ALL"],
                    "add": ["CHOWN", "FOWNER"],
                }
                assert security["runAsNonRoot"] is False
                assert security["runAsUser"] == 0
                assert security["runAsGroup"] == 0
            else:
                assert "add" not in security["capabilities"]
                assert security["runAsNonRoot"] is True
            assert security["readOnlyRootFilesystem"] is True
            if workload["kind"] in {"Deployment", "StatefulSet"} and container in pod.get("containers", []):
                assert {"startupProbe", "readinessProbe", "livenessProbe"} <= container.keys()


def test_sensitive_environment_is_secret_backed(
    server_resources: list[dict[str, Any]], edge_resources: list[dict[str, Any]]
) -> None:
    for workload in _workloads([*server_resources, *edge_resources]):
        for container in _containers(_pod_spec(workload)):
            for env in container.get("env", []):
                if _is_credential_env(env["name"]):
                    assert "value" not in env, (workload["metadata"]["name"], env["name"])
                    assert "secretKeyRef" in env.get("valueFrom", {}), env["name"]


def test_edgex_v4_database_credentials_use_generated_config_files(
    server_resources: list[dict[str, Any]],
) -> None:
    resources = _named(server_resources)
    expected_credentials = {
        "DB_USERNAME": {
            "name": "edgex-postgres-credentials",
            "key": "username",
        },
        "DB_PASSWORD": {
            "name": "edgex-postgres-credentials",
            "key": "password",
        },
    }
    expected_generator_security = {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": True,
        "runAsUser": 2002,
        "runAsGroup": 2001,
    }
    expected_generator_resources = {
        "requests": {"cpu": "25m", "memory": "32Mi"},
        "limits": {"cpu": "100m", "memory": "64Mi"},
    }
    expected_main_security = expected_generator_security
    expected_generator_patterns = {
        "core-keeper": (
            "awk '",
            'ENVIRON["DB_USERNAME"]',
            'ENVIRON["DB_PASSWORD"]',
            "yaml_scalar",
            "db_sections != 1",
            "secret_sections != 1",
            "umask 077",
            "chmod 0600",
        ),
        "core-common-config-bootstrapper": (
            "awk '",
            'ENVIRON["DB_USERNAME"]',
            'ENVIRON["DB_PASSWORD"]',
            "yaml_scalar",
            "db_sections != 1",
            "secret_sections != 1",
            "umask 077",
            "chmod 0600",
        ),
    }
    generator_commands = {}
    workloads = (
        (
            resources[("Deployment", "edgex-core-keeper")],
            "core-keeper",
            {
                "requests": {"cpu": "50m", "memory": "64Mi"},
                "limits": {"cpu": "300m", "memory": "256Mi"},
            },
            {
                "WRITABLE_INSECURESECRETS_DB_SECRETDATA_USERNAME",
                "WRITABLE_INSECURESECRETS_DB_SECRETDATA_PASSWORD",
            },
        ),
        (
            resources[("Job", "edgex-core-common-config-bootstrapper")],
            "core-common-config-bootstrapper",
            {
                "requests": {"cpu": "25m", "memory": "32Mi"},
                "limits": {"cpu": "200m", "memory": "128Mi"},
            },
            {
                "ALL_SERVICES_WRITABLE_INSECURESECRETS_DB_SECRETDATA_USERNAME",
                "ALL_SERVICES_WRITABLE_INSECURESECRETS_DB_SECRETDATA_PASSWORD",
            },
        ),
    )

    for workload, main_name, expected_main_resources, sensitive_overrides in workloads:
        pod = _pod_spec(workload)
        main = _container(workload, main_name)
        generator = next(
            container
            for container in pod["initContainers"]
            if container["name"] == "generate-database-config"
        )
        generator_env = _env(generator)
        command = " ".join(generator["command"])
        generator_commands[main_name] = command

        assert generator["image"] == main["image"]
        assert {
            name: _secret_ref(generator_env, name)
            for name in expected_credentials
        } == expected_credentials
        assert "echo" not in command
        assert "set -x" not in command
        assert "-x" not in command
        assert "tee" not in command
        assert "cat " not in command
        assert "sed -e" not in command
        assert "awk '" in command
        assert "/res/configuration.yaml" in command
        assert '/generated/configuration.yaml' in command
        assert 'ENVIRON["DB_USERNAME"]' in command
        assert 'ENVIRON["DB_PASSWORD"]' in command
        assert generator["resources"] == expected_generator_resources
        assert generator["securityContext"] == expected_generator_security
        assert pod["securityContext"] == {
            "seccompProfile": {"type": "RuntimeDefault"},
            "fsGroup": 2001,
        }
        assert _volume(pod, "generated-config") == {
            "name": "generated-config",
            "emptyDir": {},
        }
        assert generator["volumeMounts"] == [{
            "name": "generated-config",
            "mountPath": "/generated",
        }]
        assert "-cd=/generated" in main["args"]
        assert main["volumeMounts"] == [{
            "name": "generated-config",
            "mountPath": "/generated",
            "readOnly": True,
        }]
        assert main["resources"] == expected_main_resources
        assert main["securityContext"] == expected_main_security
        assert not sensitive_overrides & _env(main).keys()
        assert all(
            pattern in command for pattern in expected_generator_patterns[main_name]
        )

    assert generator_commands["core-keeper"] != (
        generator_commands["core-common-config-bootstrapper"]
    )

    bootstrapper_env = _env(_container(
        resources[("Job", "edgex-core-common-config-bootstrapper")],
        "core-common-config-bootstrapper",
    ))
    assert {
        name: bootstrapper_env[name]["value"]
        for name in (
            "ALL_SERVICES_DATABASE_HOST",
            "ALL_SERVICES_DATABASE_PORT",
            "ALL_SERVICES_DATABASE_TYPE",
            "ALL_SERVICES_DATABASE_NAME",
        )
    } == {
        "ALL_SERVICES_DATABASE_HOST": "edgex-postgres",
        "ALL_SERVICES_DATABASE_PORT": "5432",
        "ALL_SERVICES_DATABASE_TYPE": "postgres",
        "ALL_SERVICES_DATABASE_NAME": "edgex_db",
    }
@pytest.mark.parametrize(
    ("name", "template", "username_prefix"),
    [
        (
            "core-keeper",
            """Writable:
  InsecureSecrets:
    DB:
      SecretData:
        username: "postgres"
        password: "postgres"
Service:
  Host: edgex-core-keeper
""",
            "        ",
        ),
        (
            "core-common-config-bootstrapper",
            """Writable:
    InsecureSecrets:
      DB:
        SecretData:
          username: "postgres"
          password: "postgres"
    Telemetry:
      Interval: 30s
""",
            "          ",
        ),
    ],
)
def test_database_config_renderers_escape_credentials_and_restrict_output(
    tmp_path: Path, name: str, template: str, username_prefix: str
) -> None:
    username = 'user/\\&"#: value'
    password = 'password/\\&"#: value'
    result, output_path = _run_database_config_renderer(
        _database_config_generators()[name], tmp_path, template, username, password
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    rendered = output_path.read_text()
    escaped_username = username.replace("\\", "\\\\").replace('"', '\\"')
    escaped_password = password.replace("\\", "\\\\").replace('"', '\\"')
    assert rendered.count(f'{username_prefix}username: "{escaped_username}"') == 1
    assert rendered.count(f'{username_prefix}password: "{escaped_password}"') == 1
    assert yaml.safe_load(rendered)["Writable"]["InsecureSecrets"]["DB"]["SecretData"] == {
        "username": username,
        "password": password,
    }
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("username", "password", "template_mutation"),
    [
        ("", "protected-password", None),
        ("protected-username", "", None),
        ("protected-\nusername", "protected-password", None),
        ("protected-username", "protected-password", 'password: "not-postgres"'),
    ],
)
def test_database_config_renderers_reject_invalid_input_without_leaking_secrets(
    tmp_path: Path, username: str, password: str, template_mutation: str | None
) -> None:
    protected_values = [value for value in (username, password) if value]
    templates = {
        "core-keeper": """Writable:
  InsecureSecrets:
    DB:
      SecretData:
        username: "postgres"
        password: "postgres"
Service:
  Host: edgex-core-keeper
""",
        "core-common-config-bootstrapper": """Writable:
    InsecureSecrets:
      DB:
        SecretData:
          username: "postgres"
          password: "postgres"
    Telemetry:
      Interval: 30s
""",
    }

    for name, renderer in _database_config_generators().items():
        renderer_tmp_path = tmp_path / name
        template = templates[name]
        if template_mutation:
            template = template.replace('password: "postgres"', template_mutation)
        result, output_path = _run_database_config_renderer(
            renderer, renderer_tmp_path, template, username, password
        )

        assert result.returncode != 0
        assert not output_path.exists()
        assert list(output_path.parent.iterdir()) == []
        assert all(value not in result.stdout for value in protected_values)
        assert all(value not in result.stderr for value in protected_values)

def test_gateway_uses_secret_backed_edge_auth_and_tls(
    server_resources: list[dict[str, Any]],
) -> None:
    resources = _named(server_resources)
    gateway = resources[("Deployment", "edgex-ingest-gateway")]
    pod = _pod_spec(gateway)
    container = _container(gateway, "gateway")
    env = _env(container)

    assert _secret_ref(env, "TELEMETRY_DATABASE_URL") == {
        "name": "edgex-telemetry-plane-credentials",
        "key": "database-url",
    }
    edge_auth_ref = _secret_ref(env, "TELEMETRY_EDGE_AUTH_SECRETS_JSON")
    assert edge_auth_ref == {
        "name": "edgex-telemetry-edge-auth",
        "key": "edge-auth-secrets.json",
    }
    assert container["envFrom"] == [{"configMapRef": {"name": "edgex-gateway-contract"}}]
    assert resources[("ConfigMap", "edgex-gateway-contract")]["data"]["COMMAND_ENABLED"] == "false"
    assert {env[name]["value"] for name in (
        "TELEMETRY_TLS_CA_FILE", "TELEMETRY_TLS_CERT_FILE", "TELEMETRY_TLS_KEY_FILE"
    )} == {"/run/gateway-tls/ca.crt", "/run/gateway-tls/tls.crt", "/run/gateway-tls/tls.key"}
    assert _volume(pod, "gateway-tls")["secret"]["secretName"] == "edgex-ingest-gateway-tls"
    assert next(mount for mount in container["volumeMounts"] if mount["name"] == "gateway-tls")["readOnly"] is True
    for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
        probe = container[probe_name]
        assert probe["tcpSocket"] == {"port": "https"}
        assert set(probe) & {"httpGet", "tcpSocket", "exec", "grpc"} == {"tcpSocket"}


def test_database_and_bootstrap_ordering_is_explicit(
    server_resources: list[dict[str, Any]],
) -> None:
    resources = _named(server_resources)
    waits = {}
    database_waits = {}
    for name in {"edgex-core-keeper", "edgex-core-metadata", "edgex-core-data", "edgex-core-command"}:
        init_containers = _pod_spec(resources[("Deployment", name)])["initContainers"]
        waits[name] = " ".join(init_containers[0]["command"])
        database_wait = next(
            container for container in init_containers
            if container["name"] == "wait-for-database-bootstrap"
        )
        database_waits[name] = " ".join(database_wait["command"])
    bootstrap_wait = " ".join(
        _pod_spec(resources[("Job", "edgex-core-common-config-bootstrapper")])["initContainers"][0]["command"]
    )

    assert "edgex-postgres 5432" in waits["edgex-core-keeper"]
    assert "edgex-messagebus 1883" in waits["edgex-core-keeper"]
    assert "edgex-postgres 5432" in waits["edgex-core-metadata"]
    assert "edgex-core-keeper 59890" in waits["edgex-core-metadata"]
    assert "edgex-postgres 5432" in waits["edgex-core-data"]
    assert "edgex-messagebus 1883" in waits["edgex-core-data"]
    assert "edgex-core-keeper 59890" in waits["edgex-core-data"]
    assert "edgex-core-metadata 59881" in waits["edgex-core-command"]
    assert "edgex-core-keeper 59890" in bootstrap_wait
    assert all("SELECT 1" in command for command in database_waits.values())
    assert all("edgex.bootstrap" not in command for command in database_waits.values())


def test_postgres_volume_preparation_is_tightly_scoped(
    server_resources: list[dict[str, Any]],
) -> None:
    postgres = _named(server_resources)[("StatefulSet", "edgex-postgres")]
    pod = _pod_spec(postgres)
    init = next(
        container
        for container in pod["initContainers"]
        if container["name"] == "prepare-postgres-volumes"
    )
    main = _container(postgres, "postgres")

    assert init["command"] == [
        "/bin/sh",
        "-c",
        (
            "chown 70:70 /var/lib/postgresql/data /var/run/postgresql && "
            "chmod 0700 /var/lib/postgresql/data && "
            "chmod 0775 /var/run/postgresql"
        ),
    ]
    assert init["volumeMounts"] == [
        {"name": "data", "mountPath": "/var/lib/postgresql/data"},
        {"name": "run", "mountPath": "/var/run/postgresql"},
    ]
    assert init["securityContext"]["runAsUser"] == 0
    assert init["securityContext"]["runAsGroup"] == 0
    assert init["securityContext"]["capabilities"] == {
        "drop": ["ALL"],
        "add": ["CHOWN", "FOWNER"],
    }
    assert main["securityContext"]["runAsNonRoot"] is True
    assert main["securityContext"]["runAsUser"] == 70
    assert main["securityContext"]["runAsGroup"] == 70


def test_network_policies_protect_both_planes(
    server_resources: list[dict[str, Any]], edge_resources: list[dict[str, Any]]
) -> None:
    server = _named(server_resources)
    edge = _named(edge_resources)
    assert server[("NetworkPolicy", "edgex-system-default-deny-ingress")]["spec"]["podSelector"] == {}

    internal_policy = server[("NetworkPolicy", "edgex-system-internal-ingress")]["spec"]
    assert internal_policy["podSelector"] == {}
    assert internal_policy["ingress"] == [{
        "from": [{
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "edgex-system"}
            }
        }]
    }]

    assert ("NetworkPolicy", "edgex-gateway-edge-ingress") not in server

    assert edge[("NetworkPolicy", "edgex-edge-default-deny")]["spec"] == {
        "podSelector": {},
        "policyTypes": ["Ingress", "Egress"],
    }
    assert set(edge) == {
        ("Namespace", "edgex-edge"),
        ("NetworkPolicy", "edgex-edge-default-deny"),
    }
