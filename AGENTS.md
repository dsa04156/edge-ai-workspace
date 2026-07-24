# AGENTS.md

## 작업 원칙

이 저장소는 KubeEdge node/workload 관리와 EdgeX 물리 디바이스 연동을 결합한 혼합 디바이스 엣지 AI 플랫폼 PoC다.
현재 목표는 복잡한 동적 오케스트레이션을 먼저 완성하는 것이 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 운영 관점으로 보이게 만드는 것이다.

작업 전 아래 문서를 기준으로 판단한다.

- `docs/프로젝트-배경.md`: 과제 배경, 현재 목표, PoC 방향
- `docs/물리-디바이스-상태-정책.md`: EdgeX 물리 디바이스 상태와 telemetry 정책
- `docs/대시보드-판단-정책.md`: 대시보드 상태 판단 기준
- `docs/단계별-추진계획.md`: 동적 오프로딩, agent-assisted planning 후속 계획

## 현재 우선순위

1. 서비스 데모 1종을 먼저 완성한다.
2. EdgeX Device Profile/Device 등록과 Device Service 연동을 안정화한다.
3. 디바이스-서비스 연결 구조를 대시보드에서 보이게 한다.
4. 물리 디바이스 inventory, state, telemetry, command의 권위는 EdgeX로 단일화한다.
5. MapperFramework와 KubeEdge Device/DeviceStatus는 물리 연동의 legacy 경로로 두고 병행 plane이나 fallback으로 사용하지 않는다.
6. 동적 워크플로우, 오프로딩, agent-assisted planning은 후속 고도화로 둔다.

## Workflow Builder Prototype 경계

`state-aggregator` dashboard 안에 workflow stage, device/source binding, validation, execution plan을 보여주는 화면이 있더라도 이를 현재 PoC의 동적 오케스트레이션 완성 기능으로 설명하지 않는다.

현재 허용되는 범위는 다음으로 제한한다.

- EdgeX Core Metadata에 등록된 `Device` 목록과 Device Service 관리 상태 조회
- EdgeX Core Data latest Event/Reading 기준 source freshness 확인
- 물리 온디바이스, 데이터 source, resource profile 매핑 확인
- 브라우저 상태 안에서만 동작하는 workflow stage 구성과 device/resource bind/release dry-run
- 실행 전 validation과 execution plan preview
- Kubernetes apply/delete/restart, EdgeX metadata/state mutation, command publish, actuator command, runtime migration/offloading 실행 없음

이 기능을 현재 운영 기능으로 승격하려면 먼저 `docs/프로젝트-범위.md`, `docs/저장소-구조.md`, `docs/단계별-추진계획.md`에 범위, 검증 기준, 운영 책임을 명시한다.

## 구현 규칙

- 물리 디바이스는 EdgeX Core Metadata의 Device Profile과 Device로 사전 등록한다.
- EdgeX Device Service가 MQTT/Serial/Modbus/OPC-UA/RTSP endpoint의 연결, 표준화, 상태와 지원 command를 독점 관리한다.
- `edge-device-discovery`는 지정된 edge node에서 USB Serial의 `/dev/serial/by-id/*`와 I2C 버스 존재만 수동적으로 관측한다. 발견 후보는 승인 전 임시 정보이며 EdgeX inventory, Device Service 통신 성공 또는 센서 응답 근거가 아니다.
- MQTT/Modbus/OPC-UA/RTSP/REST 네트워크 endpoint는 광역 probe하지 않고 대시보드에서 후보로 직접 선언한다. 후보에는 비밀번호, token, URL userinfo와 임의 image/command/hostPath를 저장하지 않는다.
- 발견 후보의 `accepted`는 검토 상태일 뿐 자동 Device 등록이나 workload 배포가 아니다. exact node/protocol/path가 검증된 Git Adapter Catalog binding과 일치한 후보만 기존 EdgeX 등록 마법사로 넘길 수 있다.
- 발견 후보는 `edgex-device-discovery-registry` ConfigMap에 제한적으로 보관한다. 이 ConfigMap은 staging registry일 뿐 KubeEdge Device CRD나 물리 inventory authority가 아니며 최종 Device/Profile/state/Event 권위는 계속 EdgeX다.
- 발견 DaemonSet의 read-only `/dev`, `/sys` host mount는 고정된 수동 관측 agent에만 허용한다. 이 예외를 Device Service workload나 UI 입력형 hostPath로 확장하지 않는다.
- KubeEdge는 edge node와 workload 관리에만 사용한다.
- 중앙 EdgeX Core Keeper, Core Metadata, Core Data, Core Command, 내부 MessageBus, PostgreSQL과 ingest gateway는 server2에 한 세트만 배치한다.
- 중앙 내부 `edgex-messagebus`는 ClusterIP로 분리하며 고정 ClusterIP/PodIP/node IP를 데이터 경로에 사용하지 않는다.
- MQTT broker는 MQTT-only 장비 또는 명시적 local pub/sub가 필요한 노드에만 둔다. Modbus, OPC-UA, Serial, I2C 직접 Device Service에는 MQTT를 요구하지 않는다.
- `edgex-edge`에는 공식 EdgeX Device SDK 기반 `device-serial-jetson`이 배포되어 `etri-dev0001-jetorn`의 Arduino를 직접 수집한다. 이전 `edgex-edge-agent-*`, outbox PVC와 Agent 전용 Metadata bootstrap은 퇴역 상태다.
- 현재 검증된 첫 수직 슬라이스는 `arduino-001` / `etri-arduino-serial` / `device-serial-jetson`이며 Serial 정상 수집, 중앙 Core Data 저장, read-only command 조회와 dashboard freshness까지 같은 identity로 연결한다.
- RTSP frame은 Core Data로 운반하지 않고 요청 시 Workflow Pod가 직접 구독한다. 상태·분석 결과 metadata만 EdgeX Event로 전달할 수 있다.
- Device Profile의 read-only command GET은 현재값 조회에 사용한다. write command, actuator mutation, runtime migration/offloading은 별도 승인과 검증 전까지 비활성이다.
- KubeEdge는 엣지 노드와 워크로드 관리에만 사용하며 KubeEdge Device/DeviceModel/DeviceStatus를 물리 디바이스 권위나 병행 plane으로 사용하지 않는다.
- EdgeX 운영 배포의 단일 진입점은 root `edgex/k8s/kustomization.yaml`이며 Argo CD Application `edgex-telemetry`가 동기화한다.
- `edgex/telemetry-plane/`의 edge Agent 코드는 운영 경로가 아니다. 중앙 ingest gateway는 유지되지만 현재 Serial Device Service 데이터 경로에는 참여하지 않는다.
- 운영 namespace는 중앙 `edgex-system`과 물리 노드 Device Service용 `edgex-edge`로 분리한다.
- `mappers/mqttvirtual/`, mapper direct-to-Influx, `command`/`heartbeat` topic은 legacy test/integration 경로이며 fallback이 아니다.
- 대시보드의 물리 디바이스 availability는 중앙 EdgeX `adminState`, `operatingState`, Core Data 최신 Event freshness로 판단한다.
- Kubernetes node placement는 물리 디바이스 availability gate가 아닌 선택적 진단 정보다.


## Legacy / Archive Boundary

아래 경로와 주제는 현재 PoC 구현 경로가 아니라 과거 실험, 참조, 보관 자료로 본다.

- `edge-orch/workflow_executor/`: 과거 workflow 실행/orchestration 실험
- `edge-orch/workflow_reporter/`: 과거 stage event reporting 실험
- `edge-orch/placement_engine/`: 과거 placement/offloading/replanning 실험
- `workflow/`: 과거 workflow/event/scenario manifest
- `docs/archive/*`: 과거 통합 기록, 연구 초안, legacy orchestration 자료
- legacy orchestration, dynamic offloading, runtime replanning, agent-assisted planning 관련 문서와 코드

처리 규칙:

- 위 자료는 히스토리와 비교 근거로만 읽고, 현재 서비스 데모 요구사항이나 구현 목표로 해석하지 않는다.
- 현재 작업 대상으로 승격하려면 먼저 `docs/프로젝트-범위.md`와 `docs/저장소-구조.md`를 갱신해 범위 변경을 명시한다.
- 별도 승인 없이 위 경로의 내용을 dashboard, DeviceStatus, telemetry, service demo의 현재 동작으로 설명하지 않는다.
- 삭제/이동은 이 문서의 규칙만으로 수행하지 않고, 별도 정리 작업에서 승인 후 진행한다.

## 문서 표현 규칙

유지할 표현:

- 서비스 데모 우선
- 디바이스-서비스 연결 구조
- 통합 운영 가시화
- 실공장 기반 PoC
- 현장 적용성
- 생산성 향상 효과
- 단계적 확장

피할 표현:

- 완전 자율형 오케스트레이션
- LLM이 전체 제어를 수행
- 동적 워크플로우 전체 구현 완료
- 고도화 기능이 이미 실증 완료된 것처럼 보이는 표현

## 산출물 우선순위

즉시 필요한 산출물은 서비스 데모 시나리오, 디바이스 등록/관리 절차, 디바이스-서비스 바인딩 명세, 대시보드 정보 구조, 옥동 시나리오 KPI 정의다.
연차별 정량 목표, 1000 디바이스 실증 계획, 논문/특허/표준 계획은 그 다음이다.
