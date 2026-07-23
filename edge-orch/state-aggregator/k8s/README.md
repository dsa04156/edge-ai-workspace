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

## 제한된 Device Management

Dashboard의 `Device Management` 화면과 `/management/*` API는 EdgeX Core
Metadata를 대체하지 않는 제한된 onboarding UI다. Adapter Catalog에서 `installed`로
판정되고 Core Metadata에서 실행 상태가 확인된 Device Service만 dry-run 대상으로 사용한다.
현재 catalog의 검증 완료 대상은 `device-serial-jetson`과
`device-sensehat-raspi`이며 Modbus, OPC-UA, MQTT와 RTSP는 `unsupported`다.
`installed`는 Device Service runtime이 존재한다는 뜻이며 빈 route가 있다는 뜻이 아니다.
현재 Serial과 Sense HAT endpoint는 각각 `arduino-001`, `sensehat-001`로 고정되고 같은
endpoint/resource binding을 다른 Device가 이미 사용하면 dry-run이
`protocol_binding_exists`로 차단한다. 새 물리 source나 host device mount는 별도 Device
Service 배포 wave가 필요하며 이 화면이 자동으로 만들지 않는다.

기본 Deployment는 다음처럼 명시적으로 mutation을 닫는다.

```text
DEVICE_MANAGEMENT_ENABLED=false
ADAPTER_CATALOG_PATH=/app/app/config/adapter_catalog.json
```

이 상태에서도 adapter 조회와 `POST /management/devices/validate` dry-run은 가능하다.
`POST /management/devices`와 `PATCH /management/devices/{name}`은 `404`를 반환하고,
dashboard도 `DRY-RUN ONLY · MUTATION DISABLED`를 표시하며 create/PATCH control을
비활성화한다.

운영에서 mutation을 켤 때는 먼저 외부 TLS와 접근 제어가 적용된 경로를 사용하고, Git에
평문을 넣지 않는 Secret 관리 방식으로 서로 다른 두 값을 준비한다. Argo CD가 관리하는
Deployment에 다음 형태의 env를 반영한다.

```yaml
- name: DEVICE_MANAGEMENT_ENABLED
  value: "true"
- name: DEVICE_MANAGEMENT_ADMIN_TOKEN
  valueFrom:
    secretKeyRef:
      name: state-aggregator-device-management
      key: admin-token
- name: DEVICE_MANAGEMENT_HMAC_KEY
  valueFrom:
    secretKeyRef:
      name: state-aggregator-device-management
      key: hmac-key
```

두 Secret 값 중 하나라도 없으면 애플리케이션은 시작 단계에서 실패한다. 관리자 요청은
Bearer token과 요청별 `Idempotency-Key`가 모두 필요하다. token은 dashboard JavaScript
메모리에만 유지되고 URL, localStorage와 sessionStorage에는 저장하지 않는다. Device/Profile
삭제, command publish, Device Service 자동 배포, Kubernetes 또는 EdgeMesh 변경은 제공하지
않는다. `edgeAiOnboarding*`, `nodeName`, `physicalDeviceId` system tag는 사용자 PATCH 대상이
아니다. live Metadata canary는 자동 테스트에 포함하지 않는다.

Kubernetes manifests:

- `deployment.yaml`: Deployment + Service
- `rbac.yaml`: node, pod, and augmentation-resource read access
- `service-monitor.yaml`: kube-prometheus `ServiceMonitor`

Apply these manifests through the directory kustomization (or the
`edge-orch-state-aggregator` Argo CD application).

`main` CI 배포는 빌드 결과의 immutable digest를 읽고 Argo CD Application의
`spec.source.targetRevision`을 해당 Git SHA로, `spec.source.kustomize.images`를 해당
digest로 함께 갱신한다. `kubectl set image`로 Deployment를 직접 변경하면 Argo CD
`selfHeal`이 Git에 기록된 이전 image로 되돌릴 수 있으므로 운영 배포 경로로 사용하지 않는다.
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
