# State Aggregator Monitoring

`state_aggregator` exposes Prometheus-format metrics at `/metrics` and serves
EdgeX-backed physical-device state through `/state/devices` and
`/state/devices/{device_id}/telemetry`.

## Physical-device authority

EdgeX is the only physical-device data plane:

- Core Metadata supplies device inventory (`name`, `profileName`, `serviceName`,
  `protocols`, `adminState`, `operatingState`, and tags/properties diagnostics).
- Core Data supplies events (`deviceName`, `sourceName`, nanosecond `origin`, and
  typed readings).
- `LOCKED` or `DOWN` devices are unavailable/disconnected, `UNKNOWN` devices are
  degraded/unknown, and `UP` devices are available only while their latest event
  is fresh. An `UP` device with no event or a stale event is degraded.
- Optional Kubernetes node placement is display-only and never gates physical
  availability.

The Deployment remains on `etri-ser0001-cg0msb` and reaches Core Metadata and
Core Data through the `edgex-system` namespace services on ports `59881` and
`59880`. Telemetry history is read from Core Data and persisted by the central
PostgreSQL backend; this service has no separate time-series recorder.
Kubernetes access is retained only for node, workload, and
augmentation-resource observation. The service account has no KubeEdge
`Device` or `DeviceStatus` permissions, and no MapperFramework settings are
used.

The historical mqttvirtual mapper source remains in the repository, but its
kustomization renders no resources and it is not managed by the active Argo CD
applications. KubeEdge remains responsible only for Kubernetes edge nodes and
workloads.

Kubernetes manifests:

- `deployment.yaml`: Deployment + Service
- `rbac.yaml`: node, pod, and augmentation-resource read access
- `service-monitor.yaml`: kube-prometheus `ServiceMonitor`

Apply these manifests through the directory kustomization (or the
`edge-orch-state-aggregator` Argo CD application).

Expected scrape path:

```text
http://state-aggregator:8000/metrics
```

If your kube-prometheus stack uses a different `ServiceMonitor` selector label
than `release: prometheus`, update `service-monitor.yaml` to match your
cluster's Prometheus configuration.

Grafana dashboard import file:

```text
state-aggregator/grafana/state-aggregator-dashboard.json
```

Import that JSON into Grafana and bind the `Prometheus` datasource when
prompted.
