# Runtime Resource Augmentation Demo Workflow

## Purpose

This document defines the first demo workflow for runtime resource augmentation.
The workflow is a scenario contract before implementation. It explains what the
operator sees, which runtime signals are used, and what the scheduler is allowed
to decide.

This is not a manual execution flow. The dashboard must not create one-off Jobs,
send fixed sample payloads, mutate KubeEdge `Device` CRs, or directly move
workloads. The demo focuses on automatic scheduling recommendation/status based
on observed runtime resource pressure.

## Demo Story

The factory runs a Jetson-based visual inspection service on
`etri-dev0001-jetorn`. The Jetson remains the physical target edge device and
continues to own the service context.

During normal operation, telemetry and pod/service resource usage are collected.
When the inspection workload shows resource pressure, the platform evaluates
registered augmentation resources and recommends external inference/cache
support.

The operator sees this as:

```text
Jetson inspection service is under resource pressure.
The platform selected x86 GPU inference and storage cache as augmentation
candidates because their runtime instances are available and endpoint-ready.
```

## Actors And Resources

| Role | Resource |
|---|---|
| Target edge device | `etri-dev0001-jetorn` |
| Service scenario | `jetson-vision-inspection` |
| Device augmentation object | `jetson-gpu-storage-augmentation` |
| Inference augmentation resource | `vd-x86-gpu-inference` |
| Storage/cache augmentation resource | `vd-storage-cache` |
| Runtime observer | `state-aggregator` |
| Augmentation status source | `AugmentationResource` / `DeviceAugmentation` CRD status |

## Workflow

```text
1. Observe target workload
   -> collect pod/service CPU, memory, GPU, endpoint, and telemetry freshness

2. Detect resource pressure
   -> classify whether the Jetson-side inspection service needs support

3. Filter augmentation candidates
   -> read AugmentationResource status
   -> require phase=Available and endpointReady=true

4. Match capabilities
   -> inference role maps to vd-x86-gpu-inference
   -> cache/storage role maps to vd-storage-cache

5. Update recommendation/status
   -> DeviceAugmentation exposes selectedResources and pressure reason

6. Explain in dashboard
   -> show target device, pressure reason, selected resources, and apply state
```

## Scheduler Decision Model

The first scheduler version should be deterministic and rule-based.

Inputs:

- target workload identity
- target device identity
- pod/service CPU usage
- pod/service memory usage
- GPU usage or GPU capacity signal when available
- telemetry freshness
- `AugmentationResource.status.phase`
- `AugmentationResource.status.endpointReady`
- `DeviceAugmentation.status.conditions`
- selected resource role mapping

Output:

```json
{
  "scenario": "jetson-vision-inspection",
  "target_device": "etri-dev0001-jetorn",
  "recommendation": "selected",
  "pressure_reason": ["gpu_inference_pressure", "cache_required"],
  "selected_resources": [
    {
      "role": "inference",
      "name": "vd-x86-gpu-inference",
      "reason": "x86 GPU inference endpoint is available"
    },
    {
      "role": "storage",
      "name": "vd-storage-cache",
      "reason": "cache resource is available"
    }
  ],
  "apply_state": "observed-only"
}
```

`apply_state=observed-only` means the dashboard is explaining the scheduler
decision and current binding state. It does not mean the dashboard applied a
Kubernetes mutation.

## State Transitions

| State | Meaning | Dashboard message |
|---|---|---|
| `none` | No resource pressure is observed | 현재 자원증강이 필요하지 않음 |
| `candidate` | Pressure exists and one or more resources may satisfy it | 증강 후보 산출됨 |
| `selected` | Required inference/cache resources are available and selected | 증강 자원 선택됨 |
| `blocked` | Pressure exists but required resources are unavailable or not ready | 증강 불가: 후보 자원 미준비 |

## Demo Success Criteria

The demo is ready when the following are visible without manual execution:

1. The dashboard shows the target service/device for `jetson-vision-inspection`.
2. The dashboard shows observed runtime resource pressure or a normal/no-pressure state.
3. The dashboard shows which `AugmentationResource` objects were selected or blocked.
4. The dashboard explains the reason for the decision.
5. `DeviceAugmentation` status remains the source of truth for selected resource roles.
6. No per-click Kubernetes Job is created.
7. No fixed vibration sample or dummy analyzer payload is used as the scenario.

## Non-Goals

- Manual "run" button semantics
- Per-click Kubernetes Job creation
- Fixed sample analyzer calls
- Dashboard-driven Kubernetes mutation
- Runtime migration claim
- Legacy `workflow_executor` or `placement_engine` promotion
- LLM/agent-driven global control

## Implementation Plan

1. Add a runtime augmentation recommendation model to `state-aggregator`.
2. Map current pod/service resource observations to the `jetson-vision-inspection` scenario.
3. Add a rule-based scheduler function that produces `none`, `candidate`,
   `selected`, or `blocked`.
4. Expose recommendation/status through a read-only API.
5. Extend the resource augmentation dashboard to show pressure reason,
   selected resources, and apply state.
6. Add tests for normal, selected, and blocked states.
