# EdgeX Central MessageBus and Edge Device Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the EdgeX Core, internal MessageBus, and PostgreSQL workloads from the Jetson to `etri-ser0002-cgnmsb` while retaining only protocol Device Services on the sensor edge nodes for the MQTT vertical slice.

**Architecture:** The existing `edgex/k8s` Kustomize entry point remains authoritative. Core services, the internal Mosquitto MessageBus, and PostgreSQL run on server2 using amd64 EdgeX 4.0.2 images; the two ARM64 Device MQTT instances remain node-pinned to Jetson and Raspberry Pi and connect to the same central services through Kubernetes service DNS. SQLite replay and the alternate HTTPS ingest-gateway plane are not part of this slice.

**Tech Stack:** Kubernetes/KubeEdge, Kustomize, Argo CD, EdgeX Foundry 4.0.2, Mosquitto 2.0.22, PostgreSQL 16.3, Python 3.12, pytest 8, PyYAML 6.

## Global Constraints

- Every repository shell command starts with `rtk`.
- The operational render entry point remains `edgex/k8s` and the namespace remains `telemetry`.
- Central node: `etri-ser0002-cgnmsb`.
- Jetson Device MQTT node: `etri-dev0001-jetorn`.
- Sense HAT Device MQTT node: `etri-dev0003-raspi5`.
- Central EdgeX images use version `4.0.2` without the `-arm64` repository suffix.
- Device MQTT images remain `edgexfoundry/device-mqtt-arm64:4.0.2`.
- EdgeX internal MessageBus remains a ClusterIP service and is not a southbound device broker.
- Existing unrelated working-tree changes are preserved.
- Existing telemetry data does not require backup and service interruption is accepted.
- Live deletion is limited to the exact `telemetry` namespace and occurs only after render and server-side dry-run succeed.

---

## File Structure

```text
edgex/k8s/
├── core.yaml                 # central Keeper, config bootstrapper, Data, Metadata, Command
├── messagebus.yaml           # central internal MQTT MessageBus
├── postgres.yaml             # central EdgeX persistent database
├── device-mqtt.yaml          # edge-only Device MQTT instances
├── kustomization.yaml        # single operational render entry point
├── tests/
│   └── test_central_messagebus_topology.py
└── scripts/
    └── rebuild-central-messagebus.sh

docs/
├── project-context.md
├── raw-telemetry-data-plane.md
├── scope.md
├── repo-structure.md
└── ops/runbook-central-messagebus-rebuild.md
```

### Task 1: Lock the Direct MessageBus Placement Contract

**Files:**
- Create: `edgex/k8s/tests/test_central_messagebus_topology.py`
- Read: `edgex/k8s/kustomization.yaml`

**Interfaces:**
- Consumes: rendered resources from `kubectl kustomize edgex/k8s`.
- Produces: placement and architecture assertions used as the migration gate.

- [ ] **Step 1: Write the failing topology tests**

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml


K8S_DIR = Path(__file__).resolve().parents[1]
CENTRAL_NODE = "etri-ser0002-cgnmsb"
EDGE_PLACEMENT = {
    "edgex-device-mqtt": "etri-dev0001-jetorn",
    "edgex-device-mqtt-sensehat": "etri-dev0003-raspi5",
}
CENTRAL_WORKLOADS = {
    "edgex-core-keeper",
    "edgex-core-common-config-bootstrapper",
    "edgex-core-data",
    "edgex-core-metadata",
    "edgex-core-command",
    "edgex-messagebus",
    "edgex-postgres",
}


def render() -> list[dict[str, Any]]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(K8S_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def pod_spec(resource: dict[str, Any]) -> dict[str, Any]:
    return resource["spec"]["template"]["spec"]


def workloads() -> dict[str, dict[str, Any]]:
    return {
        resource["metadata"]["name"]: resource
        for resource in render()
        if resource["kind"] in {"Deployment", "StatefulSet", "Job"}
    }


def test_central_workloads_run_only_on_server2() -> None:
    rendered = workloads()
    assert CENTRAL_WORKLOADS <= rendered.keys()
    for name in CENTRAL_WORKLOADS:
        assert pod_spec(rendered[name])["nodeSelector"] == {
            "kubernetes.io/hostname": CENTRAL_NODE
        }


def test_device_services_remain_on_the_sensor_edges() -> None:
    rendered = workloads()
    for name, node in EDGE_PLACEMENT.items():
        assert pod_spec(rendered[name])["nodeSelector"] == {
            "kubernetes.io/hostname": node
        }


def test_core_images_are_amd64_and_device_images_are_arm64() -> None:
    rendered = workloads()
    for name in CENTRAL_WORKLOADS:
        containers = [
            *pod_spec(rendered[name]).get("initContainers", []),
            *pod_spec(rendered[name]).get("containers", []),
        ]
        for container in containers:
            image = container["image"]
            if "edgexfoundry/" in image:
                assert ":4.0.2" in image
                assert "-arm64" not in image
    for name in EDGE_PLACEMENT:
        assert pod_spec(rendered[name])["containers"][0]["image"] == (
            "edgexfoundry/device-mqtt-arm64:4.0.2"
        )


def test_edge_has_no_local_core_messagebus_or_database() -> None:
    rendered = workloads()
    edge_nodes = set(EDGE_PLACEMENT.values())
    for name, resource in rendered.items():
        node = pod_spec(resource).get("nodeSelector", {}).get("kubernetes.io/hostname")
        if node in edge_nodes:
            assert name in EDGE_PLACEMENT


def test_internal_messagebus_is_cluster_only() -> None:
    service = next(
        item
        for item in render()
        if item["kind"] == "Service" and item["metadata"]["name"] == "edgex-messagebus"
    )
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"] == [{"name": "mqtt", "port": 1883, "targetPort": "mqtt"}]


def test_device_services_use_the_central_configuration_and_registry() -> None:
    rendered = workloads()
    for name in EDGE_PLACEMENT:
        args = pod_spec(rendered[name])["containers"][0]["args"]
        assert "-cp=keeper.http://edgex-core-keeper:59890" in args
        assert "--registry" in args
```

- [ ] **Step 2: Run the test and verify old Jetson placement fails**

Run:

```bash
rtk python3 -m pytest edgex/k8s/tests/test_central_messagebus_topology.py -q
```

Expected: placement and image tests fail because Core, MessageBus, and PostgreSQL still target `etri-dev0001-jetorn` and use ARM64 images.

- [ ] **Step 3: Commit the failing contract**

```bash
rtk git add edgex/k8s/tests/test_central_messagebus_topology.py
rtk git commit -m "test: define central EdgeX placement contract"
```

### Task 2: Move the Core Data Plane to server2

**Files:**
- Modify: `edgex/k8s/core.yaml`
- Modify: `edgex/k8s/messagebus.yaml`
- Modify: `edgex/k8s/postgres.yaml`
- Verify: `edgex/k8s/device-mqtt.yaml`

**Interfaces:**
- Consumes: existing `telemetry` namespace service names and the Task 1 topology contract.
- Produces: one central EdgeX Core/MessageBus/PostgreSQL stack with edge-only Device MQTT workloads.

- [ ] **Step 1: Change every Core workload node selector**

In `edgex/k8s/core.yaml`, replace every Core workload selector value:

```yaml
nodeSelector:
  kubernetes.io/hostname: etri-ser0002-cgnmsb
```

This applies to Keeper, core-common-config-bootstrapper, Core Data, Core Metadata, and Core Command.

- [ ] **Step 2: Change Core EdgeX images to amd64 repositories**

Use exactly these images:

```yaml
edgexfoundry/core-keeper:4.0.2
edgexfoundry/core-common-config-bootstrapper:4.0.2
edgexfoundry/core-data:4.0.2
edgexfoundry/core-metadata:4.0.2
edgexfoundry/core-command:4.0.2
```

- [ ] **Step 3: Move MessageBus and PostgreSQL to server2**

In `edgex/k8s/messagebus.yaml` and `edgex/k8s/postgres.yaml`, set:

```yaml
nodeSelector:
  kubernetes.io/hostname: etri-ser0002-cgnmsb
```

Keep `edgex-messagebus` as `type: ClusterIP` and do not add a host port or local edge broker.

- [ ] **Step 4: Run the topology tests**

Run:

```bash
rtk python3 -m pytest edgex/k8s/tests/test_central_messagebus_topology.py -q
```

Expected: `6 passed`.

- [ ] **Step 5: Run existing manifest tests to discover incompatible legacy assertions**

Run:

```bash
rtk python3 -m pytest edgex/k8s/tests -q
```

Expected: the new topology test passes. Any failures that only assert the alternate HTTPS gateway/edge-agent topology are recorded as legacy-test conflicts and are not satisfied by reintroducing that data path.

- [ ] **Step 6: Commit central placement changes**

```bash
rtk git add edgex/k8s/core.yaml edgex/k8s/messagebus.yaml edgex/k8s/postgres.yaml
rtk git commit -m "feat: centralize EdgeX core data plane"
```

### Task 3: Align Active Documentation and Mark the HTTPS Plane Inactive

**Files:**
- Modify: `docs/project-context.md`
- Modify: `docs/scope.md`
- Modify: `docs/repo-structure.md`
- Modify: `docs/raw-telemetry-data-plane.md`
- Create: `docs/ops/runbook-central-messagebus-rebuild.md`

**Interfaces:**
- Consumes: the rendered topology from Task 2.
- Produces: one current architecture description and an exact destructive rebuild procedure.

- [ ] **Step 1: Replace the active telemetry flow in the four scope documents**

Use this canonical flow verbatim:

```text
physical sensor / PLC / equipment
  -> EdgeX Device Service on Jetson or Raspberry Pi
  -> central EdgeX MessageBus on etri-ser0002-cgnmsb
  -> Core Data -> PostgreSQL
  -> Application Service / AI consumer / state-aggregator / dashboard
```

State explicitly that `edgex/telemetry-plane`, `edgex-ingest-gateway`, and `edge-telemetry-agent` are inactive design/prototype artifacts and are not deployed by `edgex/k8s/kustomization.yaml`.

- [ ] **Step 2: Document the phase-one failure behavior**

Add these exact constraints:

```text
- Phase one has no SQLite durable replay.
- Central MessageBus/network failure may lose telemetry.
- Recovery acceptance is new Event ingestion after connectivity returns.
- SQLite replay requires a separate approved design and implementation.
```

- [ ] **Step 3: Write the rebuild runbook**

The runbook must contain these ordered commands and state that the delete target is exactly namespace `telemetry`:

```bash
rtk kubectl get nodes -o wide
rtk kubectl kustomize edgex/k8s >/tmp/edgex-central-messagebus.yaml
rtk kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml
rtk kubectl get all,pvc,configmap,secret -n telemetry
rtk kubectl delete namespace telemetry --wait=true --timeout=300s
rtk kubectl apply -k edgex/k8s
rtk kubectl rollout status deployment/edgex-core-keeper -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-core-data -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-core-metadata -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-core-command -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-messagebus -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-device-mqtt -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-device-mqtt-sensehat -n telemetry --timeout=300s
```

- [ ] **Step 4: Scan active docs for conflicting current paths**

Run:

```bash
rtk rg -n "edge-telemetry-agent|edgex-ingest-gateway|HTTPS POST /v1/events" docs --glob '!docs/archive/**' --glob '!docs/superpowers/**'
```

Expected: matches only identify those paths as inactive/prototype or historical evidence.

- [ ] **Step 5: Commit documentation**

```bash
rtk git add docs/project-context.md docs/scope.md docs/repo-structure.md docs/raw-telemetry-data-plane.md docs/ops/runbook-central-messagebus-rebuild.md
rtk git commit -m "docs: align EdgeX central message bus operations"
```

### Task 4: Add a Guarded Rebuild Helper

**Files:**
- Create: `edgex/k8s/scripts/rebuild-central-messagebus.sh`
- Create: `edgex/k8s/tests/test_rebuild_central_messagebus.py`

**Interfaces:**
- Consumes: a working `kubectl` context and `edgex/k8s` render.
- Produces: a no-op preflight by default and an exact namespace rebuild only with `--execute`.

- [ ] **Step 1: Write failing script-safety tests**

```python
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "rebuild-central-messagebus.sh"


def test_rebuild_requires_explicit_execute_flag() -> None:
    text = SCRIPT.read_text()
    assert 'if [[ "${1:-}" != "--execute" ]]' in text
    assert "kubectl delete namespace telemetry" in text
    assert "kubectl apply --dry-run=server" in text
    assert text.index("kubectl apply --dry-run=server") < text.index(
        "kubectl delete namespace telemetry"
    )


def test_rebuild_validates_exact_nodes_before_delete() -> None:
    text = SCRIPT.read_text()
    for node in (
        "etri-ser0002-cgnmsb",
        "etri-dev0001-jetorn",
        "etri-dev0003-raspi5",
    ):
        assert f"kubectl get node {node}" in text
```

- [ ] **Step 2: Run the tests and confirm the script is missing**

Run:

```bash
rtk python3 -m pytest edgex/k8s/tests/test_rebuild_central_messagebus.py -q
```

Expected: `FileNotFoundError` for `rebuild-central-messagebus.sh`.

- [ ] **Step 3: Implement the guarded helper**

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--execute" ]]; then
  echo "preflight only: pass --execute to delete and rebuild namespace telemetry"
  kubectl get nodes -o wide
  kubectl kustomize edgex/k8s >/tmp/edgex-central-messagebus.yaml
  kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml
  exit 0
fi

kubectl get node etri-ser0002-cgnmsb
kubectl get node etri-dev0001-jetorn
kubectl get node etri-dev0003-raspi5
kubectl kustomize edgex/k8s >/tmp/edgex-central-messagebus.yaml
kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml
kubectl get all,pvc,configmap,secret -n telemetry || true
kubectl delete namespace telemetry --wait=true --timeout=300s
kubectl apply -k edgex/k8s
kubectl get pods -n telemetry -o wide
```

- [ ] **Step 4: Make the helper executable and run tests**

Run:

```bash
rtk chmod +x edgex/k8s/scripts/rebuild-central-messagebus.sh
rtk python3 -m pytest edgex/k8s/tests/test_rebuild_central_messagebus.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit the guarded helper**

```bash
rtk git add edgex/k8s/scripts/rebuild-central-messagebus.sh edgex/k8s/tests/test_rebuild_central_messagebus.py
rtk git commit -m "ops: guard destructive EdgeX rebuild"
```

### Task 5: Verify and Perform the Authorized Cutover

**Files:**
- Verify: `edgex/k8s/`
- Verify: `docs/ops/runbook-central-messagebus-rebuild.md`

**Interfaces:**
- Consumes: Tasks 1-4 and the user's authorization for data loss and downtime.
- Produces: a live central Core/MessageBus deployment or an evidence-backed infrastructure blocker.

- [ ] **Step 1: Run repository verification**

```bash
rtk python3 -m pytest edgex/k8s/tests/test_central_messagebus_topology.py edgex/k8s/tests/test_rebuild_central_messagebus.py -q
rtk kubectl kustomize edgex/k8s >/tmp/edgex-central-messagebus.yaml
rtk kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml
```

Expected: all focused tests pass and server-side dry-run accepts every resource.

- [ ] **Step 2: Audit the exact live deletion target**

```bash
rtk kubectl config current-context
rtk kubectl get nodes -o wide
rtk kubectl get all,pvc -n telemetry -o wide
```

Expected: context is the intended testbed, all three target nodes exist, and only namespace `telemetry` is in deletion scope.

- [ ] **Step 3: Execute the authorized destructive rebuild**

```bash
rtk edgex/k8s/scripts/rebuild-central-messagebus.sh --execute
```

Expected: old `telemetry` resources and PVCs are deleted and the direct MessageBus topology is applied.

- [ ] **Step 4: Verify placement and service readiness**

```bash
rtk kubectl get pods -n telemetry -o wide
rtk kubectl get services -n telemetry
rtk kubectl rollout status deployment/edgex-core-keeper -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-core-data -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-core-metadata -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-core-command -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-messagebus -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-device-mqtt -n telemetry --timeout=300s
rtk kubectl rollout status deployment/edgex-device-mqtt-sensehat -n telemetry --timeout=300s
```

Expected: Core/MessageBus/PostgreSQL are on server2 and only Device MQTT workloads are on the edge nodes.

- [ ] **Step 5: Run the MQTT/Core Data smoke and dashboard check**

Use the existing canary publisher and then verify Core Data and dashboard:

```bash
rtk kubectl get --raw '/api/v1/namespaces/telemetry/services/http:edgex-core-data:59880/proxy/api/v3/event/device/name/vib-arduino-acceleration-01?limit=1'
rtk kubectl get --raw '/api/v1/namespaces/default/services/http:state-aggregator:8000/proxy/state/devices'
```

Expected: the latest Event contains typed readings and `/state/devices` reports the device using Core Metadata/Core Data evidence.

- [ ] **Step 6: Record exact evidence and remaining limitations**

Record Pod `nodeName`, image IDs, Event UUID/origin/readings, dashboard status/reason, and the explicit absence of SQLite replay. Do not claim Modbus, OPC-UA, Serial/I2C, RTSP workflow, or dynamic offloading completion.
