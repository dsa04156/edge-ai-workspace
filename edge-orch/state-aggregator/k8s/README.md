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
Kubernetes access includes node/workload observation and the separately bounded
new-Deployment Controller described below. The service account has no KubeEdge
`Device` or `DeviceStatus` permissions, and no MapperFramework settings are
used.

## 제한된 신규 Deployment Controller

`POST /api/deployments`는 `/api/placements/select` 결과가 `selected`일 때만
`edge-ai-workloads` namespace에 단일 replica Deployment를 생성하고 Pod Ready를 기다린다.
호출에는 `X-Deployment-Token`과 `Idempotency-Key`가 필요하다. token은 Git에 저장하지 않고
`default/edgex-adapter-management-auth`의 `management-hmac-key`를 재사용한다.

허용 범위:

- immutable digest와 `DEPLOYMENT_ALLOWED_IMAGE_PREFIXES` allowlist
- exact hostname `nodeSelector` + required node affinity
- 서비스 프로파일의 CPU·memory·accelerator requests
- Deployment create/get/list/watch와 Pod 상태 read

금지 범위:

- 기존 Deployment update·patch·delete
- migration, offloading, runtime replanning
- raw manifest, env, command, volume, hostPath, privilege, Service/Ingress 입력

Controller 자체와 namespace/RBAC는 Argo CD가 소유하지만, Controller가 생성한 개별
Deployment는 동적 객체이며 Argo CD manifest에 추가하지 않는다. 현재 shared token은
개발 테스트베드 경계이며 사용자별 운영 인증·인가는 아니다.

## Runtime Recommendation Engine

Service Catalog에서 policy가 활성화된 workload를 15초마다 읽어 다음 신호를 분리해
평가한다.

- apps API의 Deployment/StatefulSet desired/ready 상태
- Pod phase, Ready, restart count와 container failure reason
- Node schedulable/health와 Prometheus utilization
- 서비스 adapter의 EdgeX input freshness, model readiness, latency, backlog, throughput

ClusterRole의 apps 권한은 `get/list/watch`뿐이며 추천 엔진은 Kubernetes mutation API를
호출하지 않는다. 최신 상태와 dwell/cooldown anchor, deduplicated 판단 이력은
`state-aggregator-state` PVC의 `/app/data/runtime-recommendations.sqlite3`에 저장한다.
Deployment는 replica 1과 `Recreate` strategy로 SQLite single-writer 경계를 유지한다.
승인 기반 Execution Controller의 planId 실행 record와 감사 event는 같은 PVC의
`/app/data/runtime-executions.sqlite3`에 별도로 저장한다. Controller는 기존
`edge-ai-workloads` Deployment create/read 권한만 재사용하며 Service, Ingress, update, patch,
delete 권한은 추가하지 않는다. 실행 API는 `EXECUTION_MANAGEMENT_TOKEN`을 요구하고
`create_candidate`·`verify_ready` 이후 단계는 `unsupported_step`으로 차단한다.

```text
RUNTIME_RECOMMENDATION_ENABLED=true
RUNTIME_RECOMMENDATION_POLL_INTERVAL_SECONDS=15
RUNTIME_RECOMMENDATION_DATABASE_PATH=/app/data/runtime-recommendations.sqlite3
RUNTIME_RECOMMENDATION_HISTORY_LIMIT=1000
```

조회 API는 `/api/runtime-recommendations`,
`/api/runtime-recommendations/{serviceId}`와
`/api/runtime-recommendations/{serviceId}/history`다. 실제 신규 배포는 별도 인증된
`POST /api/deployments` 호출이며 추천 결과가 이를 자동 호출하지 않는다.

The historical mqttvirtual mapper source remains in the repository, but its
kustomization renders no resources and it is not managed by the active Argo CD
applications. KubeEdge remains responsible only for Kubernetes edge nodes and
workloads.

## Adapter Runtime과 Device 연결 관리

Dashboard `Device Management`와 `/management/*` API는 Runtime 선택부터 EdgeX Profile/Device,
Metadata readback과 first Event까지 하나의 connection operation으로 관리한다. EdgeX
Core Metadata/Core Data가 계속 물리 Device 권위다.

Device Management의 `state-aggregator`는 browser BFF이며 해당 Adapter Runtime Kubernetes
쓰기를 직접 수행하지 않는다. 내부 HMAC으로
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

두 HMAC key는 Git에 두지 않고 `default/edgex-adapter-management-auth` Secret에서 읽는다.

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

관리 mutation은 browser 관리자 token이나 `Authorization` header를 사용하지 않고 요청별
`Idempotency-Key`를 요구한다. BFF→Controller 내부 HMAC은 유지되지만 사용자 인증이
아니다. 따라서 현재 경로는 접근이 제한된 개발 테스트베드용이며 운영 노출 전 별도
사용자 인증·인가가 필요하다. Profile/Device 강제 삭제, command/actuator, EdgeMesh와 KubeEdge
Device/DeviceModel/DeviceStatus 변경은 제공하지 않는다.

운영 절차는
`docs/ops/어댑터-런타임-디바이스-연결-관리.md`를 따른다.

Kubernetes manifests:

- `deployment.yaml`: Deployment + Service
- `ingressroute.yaml`: Traefik host route for the dashboard
- `managed-workloads-namespace.yaml`: bounded dynamic workload namespace
- `state-pvc.yaml`: recommendation timer와 판단 이력 영속 저장
- `rbac.yaml`: cluster node/pod/workload read와 전용 namespace Deployment create/read
- `service-monitor.yaml`: kube-prometheus `ServiceMonitor`

Apply these manifests through the directory kustomization (or the
`edge-orch-state-aggregator` Argo CD application).

대시보드 공식 진입점은 Traefik host route다.

```text
http://aggregator.192.168.0.56.sslip.io
http://aggregator.10.254.192.217.sslip.io
```

현재 `edge-orch-state-aggregator` Argo CD Application은
`agent/edgex-central-docs` 브랜치를 추적한다. 이미지 빌드 후 immutable digest를
`deployment.yaml`에 기록해 같은 브랜치로 커밋·푸시하면 automated sync와 self-heal이
Deployment와 Traefik route를 함께 반영한다. `kubectl set image`나 IngressRoute 수동
apply는 Git 상태와 충돌하므로 운영 배포 경로로 사용하지 않는다.

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
