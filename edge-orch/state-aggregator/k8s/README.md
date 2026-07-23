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

## Adapter Runtime과 Device 연결 관리

Dashboard `Device Management`와 `/management/*` API는 Runtime 선택부터 EdgeX Profile/Device,
Metadata readback과 first Event까지 하나의 connection operation으로 관리한다. EdgeX
Core Metadata/Core Data가 계속 물리 Device 권위다.

`state-aggregator`는 browser BFF이며 Kubernetes 쓰기 권한을 갖지 않는다. 내부 HMAC으로
`edgex-edge`의 `edgex-adapter-controller`를 호출하고, Controller만 승인된
`AdapterRuntime`과 namespaced workload를 reconcile한다.

현재 Deployment 설정:

```text
DEVICE_MANAGEMENT_ENABLED=true
ADAPTER_RUNTIME_MANAGEMENT_ENABLED=true
ADAPTER_RUNTIME_MUTATION_ENABLED=true
ADAPTER_CONTROLLER_URL=http://edgex-adapter-controller.edgex-edge.svc.cluster.local:8080
ADAPTER_CATALOG_PATH=/app/app/config/adapter_catalog.json
```

세 credential은 Git에 두지 않고 `default/edgex-adapter-management-auth` Secret에서 읽는다.

- `admin-token`: dashboard 관리자 Bearer token
- `management-hmac-key`: 외부 idempotency request ID
- `internal-hmac-key`: Adapter Controller 요청 서명

Controller namespace의 같은 이름 Secret에는 동일한 `internal-hmac-key`만 둔다. 준비와
점검은 다음 스크립트를 사용한다.

```bash
edgex/k8s/scripts/provision-adapter-management-secrets.sh
edgex/k8s/scripts/preflight-adapter-management-secrets.sh
```

기존 Secret이 있으면 provisioning은 기본적으로 회전을 거부한다. 의도적 회전은
`--replace`와 두 Deployment 동시 rollout 절차로만 수행한다. 필요한 key가 없으면
Kubernetes가 Pod 시작을 차단한다.

현재 `device-serial-jetson`과 `device-sensehat-raspi`는 Argo CD 소유 external runtime이다.
대시보드는 이들을 조회·재사용하지만 restart/retire하지 않는다. Controller가 만든 runtime만
재시작할 수 있고 EdgeX consumer가 0개일 때 exact-name 확인 뒤 퇴역한다. Core Metadata
조회 장애는 consumer 0으로 간주하지 않는다.

요청 schema에는 raw manifest, image, command, privilege, hostPath, hostNetwork,
ClusterIP/PodIP가 없다. target node와 device path는 Git의 `hardwareBindingId` allowlist로
고정한다. KubeEdge target node가 Ready이고 Device Service가 Core Metadata에 등록된 뒤에만
connection을 진행한다. Modbus, OPC-UA, MQTT와 RTSP는 실장비 검증 전까지 배포가
`BLOCKED`다.

관리자 mutation은 Bearer token과 요청별 `Idempotency-Key`를 모두 요구한다. token은
dashboard JavaScript memory에만 유지되고 URL, localStorage와 sessionStorage에는 저장하지
않는다. Profile/Device 강제 삭제, command/actuator, EdgeMesh와 KubeEdge
Device/DeviceModel/DeviceStatus 변경은 제공하지 않는다.

운영 절차는
`docs/ops/어댑터-런타임-디바이스-연결-관리.md`를 따른다.

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

워크플로 파일 자체가 바뀌어 legacy `mqttvirtual` 단계가 평가되더라도 현재 클러스터에
`mqttvirtual-mapper` DaemonSet이 없으면 rollout을 명시적으로 건너뛴다. 이 guard는
DaemonSet을 생성하거나 MQTT 경로를 다시 활성화하지 않는다.

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
