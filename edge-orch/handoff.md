# Handoff

## Current status

This repository now has eight working pieces connected end-to-end:

1. `state_aggregator` (With Automated Node Discovery)
2. `workflow_reporter`
3. `placement_engine`
4. `workflow_executor` (With SQLite persistence & Replanning)
5. `vision_stage_runner` (Multi-arch synthetic stage payload)
6. **GitHub Actions CI Pipeline** (Self-hosted multi-arch buildx)
7. **ArgoCD Image Updater** (Automated tag tracking & rollout)
8. **Traefik Gateway** (Standardized access via sslip.io)

The current system supports:
- Prometheus metric ingestion into `state_aggregator`
- Normalized node/workflow state exposure
- Automated multi-arch container builds & registry pushes
- Automated deployment rollouts via ArgoCD Image Updater
- Heuristic placement & stage-boundary replanning
- Standardized domain access (`*.sslip.io`) without local hosts modification
- Persistent execution state tracking in SQLite

## What was implemented

### 1. `state_aggregator`

Location:
- [state-aggregator/app/main.py](/home/etri/jinuk/edge-orch/state-aggregator/app/main.py)
- [state-aggregator/app/service.py](/home/etri/jinuk/edge-orch/state-aggregator/app/service.py)
- [state-aggregator/app/prometheus.py](/home/etri/jinuk/edge-orch/state-aggregator/app/prometheus.py)
- [state-aggregator/app/kube.py](/home/etri/jinuk/edge-orch/state-aggregator/app/kube.py) (New: Dynamic Node Discovery)

Implemented:
- **Dynamic Node Discovery**: Uses K8s API (`KubeClient`) to detect nodes and roles in real-time. No longer requires `instance_map.json`.
- Periodic Prometheus polling & node metric normalization.
- Workflow event ingestion & summary state generation.
- `/metrics` endpoint in Prometheus exposition format.

### 2. Grafana dashboard

Location:
- [state-aggregator/grafana/state-aggregator-dashboard.json](/home/etri/jinuk/edge-orch/state-aggregator/grafana/state-aggregator-dashboard.json)

Includes panels for:
- Tracked nodes (Auto-updating)
- Hotspot nodes & SLA risk workflows
- CPU/Memory/Network throughput
- Normalized node state & Workflow control state

### 3. `workflow_reporter`

Location:
- [workflow_reporter/workflow_reporter/client.py](/home/etri/jinuk/edge-orch/workflow_reporter/workflow_reporter/client.py)
- [workflow_reporter/workflow_reporter/demo_workflow.py](/home/etri/jinuk/edge-orch/workflow_reporter/workflow_reporter/demo_workflow.py)

Implemented:
- `stage_start`, `stage_end`, `migration_event`, `failure_event`, `workflow_end`.
- 5-stage vision pipeline demo runner.

### 4. `placement_engine`

Location:
- [placement_engine/placement_engine/engine.py](/home/etri/jinuk/edge-orch/placement_engine/placement_engine/engine.py)
- [placement_engine/placement_engine/main.py](/home/etri/jinuk/edge-orch/placement_engine/placement_engine/main.py)

Implemented:
- Heuristic stage placement logic (`/placement/decide`).
- Multi-stage replanning logic (`/placement/replan`).

### 5. `workflow_executor`

Location:
- [workflow_executor/workflow_executor/main.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/main.py)
- [workflow_executor/workflow_executor/service.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/service.py)
- [workflow_executor/workflow_executor/storage.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/storage.py) (New: SQLite persistence)

Implemented:
- **Replanning Hook**: Refreshes placement decisions at stage boundaries.
- **SQLite Persistence**: Execution history is recorded in `workflow_state.db`.
- Kubernetes `Job` creation per stage with `imagePullPolicy: Always`.

### 6. `vision_stage_runner`

Location:
- [vision_stage_runner/vision_stage_runner/main.py](/home/etri/jinuk/edge-orch/vision_stage_runner/vision_stage_runner/main.py)

Implemented:
- Multi-arch image build for `linux/amd64` and `linux/arm64`.
- Reusable synthetic stage logic keyed by `workflow_id`.

## What was actually verified

### Verified on the cluster
- **CI/CD Pipeline**: `git push` -> GitHub Actions Build (Buildx) -> Registry Push -> ArgoCD Image Updater Rollout.
- **Dynamic Node Discovery**: Added new worker node `etri-ser0002-cgnmsb` and verified it appeared in dashboard automatically.
- **Heterogeneous Execution**: Successfully ran workflow across x86 server and Raspberry Pi 5.

## Latest successful executor run
Workflow ID: `wf-exec-demo-001`
- `capture` -> `etri-dev0002-raspi5` (Job: `wf-exec-demo-001-capture-XXXXXX`)
- `preprocess` -> `etri-dev0002-raspi5`
- `inference` -> `etri-ser0001-cg0msb`
- `postprocess` -> `etri-ser0001-cg0msb`
- `result_delivery` -> `etri-dev0002-raspi5`

## Images and deployments
We use a **Tag-based Tracking** strategy with ArgoCD Image Updater.
- **Registry**: `192.168.0.56:5000`
- **Tag**: `latest` (Tracked by Digest)
- **ArgoCD Apps**: Managed in `/home/etri/jinuk/edge-orch-argocd/argocd-apps.yaml`.

## Known limitations
1. **Live Migration**: No checkpoint-based migration; moves occur at stage boundaries only.
2. **Data passing**: Stages still use local synthetic logic; no shared storage (Redis/MinIO) yet.
3. **Synchronous Executor**: `workflow_executor` waits for Job completion synchronously.

## Important operational notes

### Service Access (sslip.io)
No need to modify `hosts` files. Access via:
- **ArgoCD**: [http://argocd.192.168.0.56.sslip.io](http://argocd.192.168.0.56.sslip.io)
- **Grafana**: [http://grafana.192.168.0.56.sslip.io](http://grafana.192.168.0.56.sslip.io)
- **Prometheus**: [http://prometheus.192.168.0.56.sslip.io](http://prometheus.192.168.0.56.sslip.io)

### Triggering a manual Workflow
```bash
curl -sS -X POST http://executor.192.168.0.56.sslip.io/execute/workflow \
  -H 'content-type: application/json' \
  --data @/home/etri/jinuk/edge-orch/workflow_executor/k8s/demo-request.json
```

## Recommended next steps
1. **Data Persistence Layer**: Implement **Redis** for sharing image data between stages.
2. **Real AI Integration**: Replace `vision_stage_runner` loops with actual ONNX/PyTorch inference code.
3. **Overload Scenarios**: Create experiment scripts to trigger intentional node stress.

## Latest Updates (April 2026)
- **Full CI/CD Automation**: Integrated GitHub Actions (Multi-arch) and ArgoCD Image Updater.
- **Standardized Entrypoint**: Traefik Gateway with `IngressRoute` and `sslip.io` domains.
- **Dynamic Infrastructure**: Automated node discovery and cloud-tier node pinning.
 Here is the updated code:
# Handoff

## Current status

This repository now has eight working pieces connected end-to-end:

1. `state_aggregator` (With Automated Node Discovery)
2. `workflow_reporter`
3. `placement_engine`
4. `workflow_executor` (With SQLite persistence & Replanning)
5. `vision_stage_runner` (Multi-arch synthetic stage payload)
6. **GitHub Actions CI Pipeline** (Self-hosted multi-arch buildx)
7. **ArgoCD Image Updater** (Automated tag tracking & rollout)
8. **Traefik Gateway** (Standardized access via sslip.io)

The current system supports:
- Prometheus metric ingestion into `state_aggregator`
- Normalized node/workflow state exposure
- Automated multi-arch container builds & registry pushes
- Automated deployment rollouts via ArgoCD Image Updater
- Heuristic placement & stage-boundary replanning
- Standardized domain access (`*.sslip.io`) without local hosts modification
- Persistent execution state tracking in SQLite

## What was implemented

### 1. `state_aggregator`

Location:
- [state-aggregator/app/main.py](/home/etri/jinuk/edge-orch/state-aggregator/app/main.py)
- [state-aggregator/app/service.py](/home/etri/jinuk/edge-orch/state-aggregator/app/service.py)
- [state-aggregator/app/prometheus.py](/home/etri/jinuk/edge-orch/state-aggregator/app/prometheus.py)
- [state-aggregator/app/kube.py](/home/etri/jinuk/edge-orch/state-aggregator/app/kube.py) (New: Dynamic Node Discovery)

Implemented:
- **Dynamic Node Discovery**: Uses K8s API (`KubeClient`) to detect nodes and roles in real-time. No longer requires `instance_map.json`.
- Periodic Prometheus polling & node metric normalization.
- Workflow event ingestion & summary state generation.
- `/metrics` endpoint in Prometheus exposition format.

### 2. Grafana dashboard

Location:
- [state-aggregator/grafana/state-aggregator-dashboard.json](/home/etri/jinuk/edge-orch/state-aggregator/grafana/state-aggregator-dashboard.json)

Includes panels for:
- Tracked nodes (Auto-updating)
- Hotspot nodes & SLA risk workflows
- CPU/Memory/Network throughput
- Normalized node state & Workflow control state

### 3. `workflow_reporter`

Location:
- [workflow_reporter/workflow_reporter/client.py](/home/etri/jinuk/edge-orch/workflow_reporter/workflow_reporter/client.py)
- [workflow_reporter/workflow_reporter/demo_workflow.py](/home/etri/jinuk/edge-orch/workflow_reporter/workflow_reporter/demo_workflow.py)

Implemented:
- `stage_start`, `stage_end`, `migration_event`, `failure_event`, `workflow_end`.
- 5-stage vision pipeline demo runner.

### 4. `placement_engine`

Location:
- [placement_engine/placement_engine/engine.py](/home/etri/jinuk/edge-orch/placement_engine/placement_engine/engine.py)
- [placement_engine/placement_engine/main.py](/home/etri/jinuk/edge-orch/placement_engine/placement_engine/main.py)

Implemented:
- Heuristic stage placement logic (`/placement/decide`).
- Multi-stage replanning logic (`/placement/replan`).

### 5. `workflow_executor`

Location:
- [workflow_executor/workflow_executor/main.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/main.py)
- [workflow_executor/workflow_executor/service.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/service.py)
- [workflow_executor/workflow_executor/storage.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/storage.py) (New: SQLite persistence)

Implemented:
- **Replanning Hook**: Refreshes placement decisions at stage boundaries.
- **SQLite Persistence**: Execution history is recorded in `workflow_state.db`.
- Kubernetes `Job` creation per stage with `imagePullPolicy: Always`.

### 6. `vision_stage_runner`

Location:
- [vision_stage_runner/vision_stage_runner/main.py](/home/etri/jinuk/edge-orch/vision_stage_runner/vision_stage_runner/main.py)

Implemented:
- Multi-arch image build for `linux/amd64` and `linux/arm64`.
- Reusable synthetic stage logic keyed by `workflow_id`.

## What was actually verified

### Verified on the cluster
- **CI/CD Pipeline**: `git push` -> GitHub Actions Build (Buildx) -> Registry Push -> ArgoCD Image Updater Rollout.
- **Dynamic Node Discovery**: Added new worker node `etri-ser0002-cgnmsb` and verified it appeared in dashboard automatically.
- **Heterogeneous Execution**: Successfully ran workflow across x86 server and Raspberry Pi 5.

## Latest successful executor run
Workflow ID: `wf-exec-demo-001`
- `capture` -> `etri-dev0002-raspi5` (Job: `wf-exec-demo-001-capture-XXXXXX`)
- `preprocess` -> `etri-dev0002-raspi5`
- `inference` -> `etri-ser0001-cg0msb`
- `postprocess` -> `etri-ser0001-cg0msb`
- `result_delivery` -> `etri-dev0002-raspi5`

## Images and deployments
We use a **Tag-based Tracking** strategy with ArgoCD Image Updater.
- **Registry**: `192.168.0.56:5000`
- **Tag**: `latest` (Tracked by Digest)
- **ArgoCD Apps**: Managed in `/home/etri/jinuk/edge-orch-argocd/argocd-apps.yaml`.

## Known limitations
1. **Live Migration**: No checkpoint-based migration; moves occur at stage boundaries only.
2. **Data passing**: Stages still use local synthetic logic; no shared storage (Redis/MinIO) yet.
3. **Synchronous Executor**: `workflow_executor` waits for Job completion synchronously.

## Important operational notes

### Service Access (sslip.io)
No need to modify `hosts` files. Access via:
- **ArgoCD**: [http://argocd.192.168.0.56.sslip.io](http://argocd.192.168.0.56.sslip.io)
- **Grafana**: [http://grafana.192.168.0.56.sslip.io](http://grafana.192.168.0.56.sslip.io)
- **Prometheus**: [http://prometheus.192.168.0.56.sslip.io](http://prometheus.192.168.0.56.sslip.io)

### Triggering a manual Workflow
```bash
curl -sS -X POST http://executor.192.168.0.56.sslip.io/execute/workflow \
  -H 'content-type: application/json' \
  --data @/home/etri/jinuk/edge-orch/workflow_executor/k8s/demo-request.json
```

## Recommended next steps
1. **Data Persistence Layer**: Implement **Redis** for sharing image data between stages.
2. **Real AI Integration**: Replace `vision_stage_runner` loops with actual ONNX/PyTorch inference code.
3. **Overload Scenarios**: Create experiment scripts to trigger intentional node stress.

## Latest Updates (April 2026)
- **Full CI/CD Automation**: Integrated GitHub Actions (Multi-arch) and ArgoCD Image Updater.
- **Standardized Entrypoint**: Traefik Gateway with `IngressRoute` and `sslip.io` domains.
- **Dynamic Infrastructure**: Automated node discovery and cloud-tier node pinning.
- **Network Recovery**: Documented E2E resolution for EdgeMesh/DNS failures in [troubleshooting-network.md](docs/troubleshooting-network.md).
