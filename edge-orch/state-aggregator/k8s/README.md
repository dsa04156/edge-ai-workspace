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
Core Data through the `edgex-system` namespace ClusterIP services on ports
`59881` and `59880`. Optional InfluxDB resource-profile recording is disabled
until an explicit central endpoint and runtime Secret are provisioned.
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

`main` CI 배포는 빌드 결과의 immutable digest를 읽고 Argo CD Application의
`spec.source.targetRevision`을 해당 Git SHA로, `spec.source.kustomize.images`를 해당
digest로 함께 갱신한다. `kubectl set image`로 Deployment를 직접 변경하면 Argo CD
`selfHeal`이 Git에 기록된 image로 되돌릴 수 있으므로 운영 배포 경로로 사용하지 않는다.
CI는 Argo CD refresh 뒤 Deployment가 목표 digest를 가리키는지 확인한 다음 rollout 완료를
기다린다.

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
