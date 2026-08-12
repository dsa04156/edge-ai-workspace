from __future__ import annotations

import os
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

import yaml

SIMULATOR_DIR = (
    Path(__file__).resolve().parents[1] / "base" / "modbus-simulator"
)
K8S_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIMULATOR_DIR))

from server import ModbusTCPServer, RegisterBank, parse_unit_ids  # noqa: E402


def render(path: Path) -> list[dict]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def request_register(
    address: tuple[str, int],
    *,
    function: int = 3,
    start: int = 0,
    count: int = 1,
    unit_id: int = 1,
) -> bytes:
    transaction_id = 7
    pdu = struct.pack(">BHH", function, start, count)
    frame = struct.pack(
        ">HHHB",
        transaction_id,
        0,
        len(pdu) + 1,
        unit_id,
    ) + pdu
    with socket.create_connection(address, timeout=2) as connection:
        connection.sendall(frame)
        header = connection.recv(7)
        _, protocol_id, length, response_unit = struct.unpack(">HHHB", header)
        payload = connection.recv(length - 1)
    assert protocol_id == 0
    assert response_unit == unit_id
    return payload


def running_server() -> tuple[ModbusTCPServer, threading.Thread]:
    server = ModbusTCPServer(
        ("127.0.0.1", 0),
        unit_ids={1, 2, 3},
        registers=RegisterBank(temperature_provider=lambda: 235),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_reads_temperature_holding_register() -> None:
    server, thread = running_server()
    try:
        payload = request_register(server.server_address)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload == b"\x03\x02\x00\xeb"


def test_rejects_unsupported_function_and_range() -> None:
    server, thread = running_server()
    try:
        unsupported = request_register(server.server_address, function=6)
        illegal_address = request_register(server.server_address, start=10)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert unsupported == b"\x86\x01"
    assert illegal_address == b"\x83\x02"


def test_serves_a_second_virtual_sensor_unit() -> None:
    server, thread = running_server()
    try:
        payload = request_register(server.server_address, unit_id=2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload == b"\x03\x02\x00\xeb"


def test_serves_a_third_virtual_sensor_unit() -> None:
    server, thread = running_server()
    try:
        payload = request_register(server.server_address, unit_id=3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload == b"\x03\x02\x00\xeb"


def test_rejects_wrong_unit_id() -> None:
    server, thread = running_server()
    try:
        payload = request_register(server.server_address, unit_id=4)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload == b"\x83\x0b"


def test_parses_validated_unit_id_list() -> None:
    assert parse_unit_ids("1, 2,3,2") == {1, 2, 3}

    for invalid in ("", "1,invalid", "248"):
        try:
            parse_unit_ids(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{invalid!r} must be rejected")


def test_development_overlay_is_node_pinned_and_non_privileged() -> None:
    resources = {
        (item["kind"], item["metadata"]["name"]): item
        for item in render(
            K8S_DIR / "overlays" / "development" / "modbus-simulator"
        )
    }
    deployment = resources[("Deployment", "edge-modbus-simulator")]
    service = resources[("Service", "edge-modbus-simulator")]
    policy = resources[("NetworkPolicy", "edge-modbus-simulator")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]

    assert deployment["metadata"]["namespace"] == "edgex-edge"
    assert deployment["spec"]["template"]["spec"]["nodeSelector"] == {
        "kubernetes.io/hostname": "etri-dev0001-jetorn"
    }
    assert container["image"] == (
        "docker.io/library/python:3.12-alpine@sha256:"
        "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
    )
    assert container["securityContext"]["privileged"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert {"name": "MODBUS_UNIT_IDS", "value": "1,2,3"} in container["env"]
    assert "clusterIP" not in service["spec"]
    assert service["spec"]["ports"] == [
        {"name": "modbus-tcp", "port": 1502, "targetPort": "modbus-tcp"}
    ]
    assert policy["spec"]["ingress"][0]["from"] == [
        {
            "podSelector": {
                "matchLabels": {
                    "edgeai.etri.re.kr/adapter": "modbus"
                }
            }
        }
    ]


def test_modbus_simulator_is_not_part_of_the_default_operational_render() -> None:
    names = {
        (item["kind"], item["metadata"]["name"])
        for item in render(K8S_DIR)
    }

    assert ("Deployment", "edge-modbus-simulator") not in names
    assert ("Service", "edge-modbus-simulator") not in names
