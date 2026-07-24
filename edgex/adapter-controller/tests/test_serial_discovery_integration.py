from __future__ import annotations

import json
import os
import select
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.catalog import RuntimeTemplateCatalog
from app.discovery import DeviceCandidateRegistry
from app.discovery_models import DiscoveryObservation, NodeDiscoveryReport

from fakes import FakeKubernetesGateway


CONTROLLER_DIR = Path(__file__).resolve().parents[1]
AGENT_DIR = CONTROLLER_DIR.parent / "device-discovery-agent"


@contextmanager
def serial_simulator(link: Path):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "simulators.serial_arduino",
            "--device-id",
            "stable-arduino-e2e",
            "--link",
            str(link),
        ],
        cwd=AGENT_DIR,
        env={**os.environ, "PYTHONPATH": "."},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 5)
        assert ready, "Serial simulator did not become ready"
        assert process.stdout is not None
        assert process.stdout.readline().strip().startswith("/dev/pts/")
        yield
    finally:
        process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)


def scan_agent(dev_root: Path, sys_root: Path) -> list[dict]:
    script = """
import json
import sys
from pathlib import Path
from app.scanner import scan_serial

plan = {
    "enabled": True,
    "allowedVidPid": [],
    "baudRates": [115200],
    "manifestProbeEnabled": True,
    "manifestCommand": "WHOAMI",
    "manifestTimeoutSeconds": 0.8,
}
candidates, errors = scan_serial(Path(sys.argv[1]), Path(sys.argv[2]), plan)
print(json.dumps({"candidates": candidates, "errors": errors}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(dev_root), str(sys_root)],
        cwd=AGENT_DIR,
        env={**os.environ, "PYTHONPATH": "."},
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    return payload["candidates"]


def report(candidates: list[dict]) -> NodeDiscoveryReport:
    return NodeDiscoveryReport(
        node_name="etri-dev0001-jetorn",
        agent_id="discovery/e2e",
        observed_at=datetime.now(timezone.utc),
        candidates=[
            DiscoveryObservation.model_validate(item)
            for item in candidates
        ],
        scan_errors=[],
    )


def test_pty_agent_report_disconnect_and_reconnect_preserve_candidate_id(
    tmp_path,
):
    link = (
        tmp_path
        / "dev"
        / "serial"
        / "by-id"
        / "usb-Arduino-stable-e2e"
    )
    link.parent.mkdir(parents=True)
    sys_root = tmp_path / "sys"
    catalog = RuntimeTemplateCatalog.load(
        CONTROLLER_DIR / "config/runtime_templates.json"
    )
    registry = DeviceCandidateRegistry(
        catalog,
        FakeKubernetesGateway(),
        candidate_limit=10,
    )

    with serial_simulator(link):
        first = registry.ingest_report(
            report(scan_agent(tmp_path / "dev", sys_root))
        ).candidates[0]

    disconnected = registry.ingest_report(report([])).candidates[0]

    with serial_simulator(link):
        reconnected = registry.ingest_report(
            report(scan_agent(tmp_path / "dev", sys_root))
        ).candidates[0]

    assert first.hardware_id == "usb-Arduino-stable-e2e"
    assert first.model == "arduino-multisensor-v1"
    assert disconnected.state == "STALE"
    assert reconnected.candidate_id == first.candidate_id
    assert reconnected.state != "STALE"
