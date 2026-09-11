<!-- Paths in this guide are relative to the repository root. -->

## 구현 규칙

- 물리 디바이스는 EdgeX Core Metadata의 Device Profile과 Device로 사전 등록한다.
- EdgeX Device Service가 MQTT/Serial/Modbus/OPC-UA/RTSP endpoint의 연결, 표준화, 상태와 지원 command를 독점 관리한다.
- 일반 `edge-device-discovery`는 지정된 모든 edge node에서 USB Serial의 `/dev/serial/by-id/*`를 읽기 전용으로 수동적(passive) 관측한다. dev0003의 별도 I2C Agent만 allowlist bus/address와 read-only chip identity를 확인한다. 발견 후보는 승인 전 임시 정보이며 EdgeX inventory, Device Service 통신 성공 또는 센서 응답 근거가 아니다.
- MQTT/Modbus/OPC-UA/RTSP/REST 네트워크 endpoint는 광역 probe하지 않고 대시보드에서 후보로 직접 선언한다. 후보에는 비밀번호, token, URL userinfo와 임의 image/command/hostPath를 저장하지 않는다.
- 발견 후보의 `accepted`는 검토 상태일 뿐 자동 Device 등록이나 workload 배포가 아니다. exact node/protocol/path가 검증된 Git Adapter Catalog binding과 일치한 후보만 기존 EdgeX 등록 마법사로 넘길 수 있다.
- 발견 후보, 상태 이력, 승인과 등록 Saga는 Adapter Controller의 PVC SQLite에 보관한다. 기존 `edgex-device-discovery-registry` ConfigMap은 최초 기동의 1회 migration 입력일 뿐 권위 저장소가 아니며 최종 Device/Profile/state/Event 권위는 계속 EdgeX다.
- 발견 DaemonSet의 read-only `/dev`, `/sys` host mount는 고정된 수동 관측 agent에만 허용한다. 이 예외를 Device Service workload나 UI 입력형 hostPath로 확장하지 않는다.
- 중앙 EdgeX Core Keeper, Core Metadata, Core Data, Core Command, 내부 MessageBus,
  PostgreSQL과 ingest gateway는 `etri-ser0002-cgnmsb`에 한 세트만 배치한다.
- 중앙 내부 `edgex-messagebus`는 ClusterIP로 분리하며 고정 ClusterIP/PodIP/node IP를 데이터 경로에 사용하지 않는다.
- MQTT broker는 MQTT-only 장비 또는 명시적 local pub/sub가 필요한 노드에만 둔다. Modbus, OPC-UA, Serial, I2C 직접 Device Service에는 MQTT를 요구하지 않는다.
- `edgex-edge`에는 공식 EdgeX Device SDK 기반 `device-serial-jetson`과
  `device-sensehat-raspi`가 배포되어 각각 `etri-dev0001-jetorn`의 Arduino Serial과
  `etri-dev0003-raspi5`의 Sense HAT I2C를 직접 수집한다. 이전 `edgex-edge-agent-*`,
  outbox PVC와 Agent 전용 Metadata bootstrap은 퇴역 상태다.
- 현재 검증된 수직 슬라이스는 `arduino-001` → `device-serial-jetson`과
  `sensehat-001` → `device-sensehat-raspi`다. 세부 EdgeX Device 목록과 resource 계약은
  `docs/프로젝트-범위.md`를 따르며, 중앙 Core Data Event와 dashboard freshness까지 같은
  물리 source identity로 연결한다.
- RTSP frame은 Core Data로 운반하지 않고 승인된 소비 서비스 Pod가 요청 시 직접
  구독한다. 상태·분석 결과 metadata만 EdgeX Event로 전달할 수 있다.
- Device Profile의 read-only command GET은 현재값 조회에 사용한다. write command, actuator mutation, runtime migration/offloading은 별도 승인과 검증 전까지 비활성이다.
- KubeEdge는 엣지 노드와 워크로드 관리에만 사용하며 KubeEdge Device/DeviceModel/DeviceStatus를 물리 디바이스 권위나 병행 plane으로 사용하지 않는다.
- EdgeX 운영 배포의 단일 진입점은 root `edgex/k8s/kustomization.yaml`이며 Argo CD Application `edgex-telemetry`가 동기화한다.
- `edgex/telemetry-plane/`의 edge Agent 코드는 운영 경로가 아니다. 중앙 ingest gateway는 유지되지만 현재 Serial Device Service 데이터 경로에는 참여하지 않는다.
- 운영 namespace는 중앙 `edgex-system`과 물리 노드 Device Service용 `edgex-edge`로 분리한다.
- `mappers/mqttvirtual/`, mapper direct-to-Influx, `command`/`heartbeat` topic은 legacy test/integration 경로이며 fallback이 아니다.
- 대시보드 분류상 물리 디바이스 노드 availability는 Kubernetes/KubeEdge와 Prometheus
  node snapshot으로 판단한다.
- 센서 디바이스 availability는 중앙 EdgeX `adminState`, `operatingState`, Core Data
  최신 Event freshness로 판단하며 Kubernetes node placement를 gate로 사용하지 않는다.
- transport 연결 복구는 `docs/디바이스-연결-복구-표준.md`의 공통 상태와 측정 경계를
  따른다. `RecoveryStrategy`는 의미 기반 allowlist로 선언하고 Device Service adapter가
  고정 동작으로 구현한다. 대시보드나 등록 입력에서 임의 Serial byte, MQTT topic 또는
  command를 받지 않는다. protocol 행이나 설계 계약만 존재하는 기능을 구현 완료로
  설명하지 않고 실제 adapter·binding·자동시험·실장비 반복시험을 모두 확인한다.
