# AGENTS.md

## 작업 원칙

이 저장소는 KubeEdge 기반 혼합 디바이스 엣지 AI 플랫폼 PoC다.
현재 목표는 복잡한 동적 오케스트레이션을 먼저 완성하는 것이 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 운영 관점으로 보이게 만드는 것이다.

작업 전 아래 문서를 기준으로 판단한다.

- `docs/project-context.md`: 과제 배경, 현재 목표, PoC 방향
- `docs/device-status-policy.md`: DeviceStatus와 telemetry 분리 정책
- `docs/dashboard-policy.md`: 대시보드 상태 판단 기준
- `docs/roadmap.md`: 동적 오프로딩, agent-assisted planning 후속 계획

## 현재 우선순위

1. 서비스 데모 1종을 먼저 완성한다.
2. 디바이스 등록/관리 체계를 안정화한다.
3. 디바이스-서비스 연결 구조를 대시보드에서 보이게 한다.
4. DeviceStatus는 저빈도 운영 snapshot으로 제한한다.
5. raw telemetry는 MQTT/InfluxDB data-plane으로 처리한다.
6. 동적 워크플로우, 오프로딩, agent-assisted planning은 후속 고도화로 둔다.

## 구현 규칙

- KubeEdge `Device`는 현재 사전 등록 방식으로 운영한다.
- Jetson 디바이스는 `etri-dev0001-jetorn`, Raspberry Pi 디바이스는 `etri-dev0002-raspi5`에 할당한다.
- 테스트 publisher는 실행한 서버의 로컬 mosquitto(`127.0.0.1:1883`)로 publish한다.
- `factory/devices/{device-name}/telemetry`는 telemetry 입력 topic이다.
- `factory/devices/{device-name}/command`는 command topic이다.
- `factory/devices/{device-name}/heartbeat`는 테스트 publisher 보조 heartbeat이며 KubeEdge Device manifest에는 직접 연결하지 않는다.
- raw telemetry 값을 DeviceStatus에 올리지 않는다.
- `status.state=online`만으로 healthy 판단하지 않는다.

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
