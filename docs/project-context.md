# Project Context

## 한 줄 정의

현재 단계는 혼합 디바이스 엣지 AI 플랫폼의 전체 동적 오케스트레이션을 먼저 완성하는 단계가 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 가시화하며 현장 생산성 향상 효과를 설명 가능한 서비스 데모로 만드는 단계다.

장기적으로는 이 기반 위에 동적 워크플로우, 가상화, 스케줄링, 오프로딩 고도화를 붙인다.

## 대상 환경

- x86 엣지 AI 서버
- Jetson 엣지 AI 디바이스
- Raspberry Pi 5 엣지 디바이스
- 물리 센서 디바이스
- 가상 디바이스 / 디바이스트윈

현재 테스트베드 노드:

| 구분 | hostname | 역할 |
|---|---|---|
| 서버 1 | `etri-ser0001-cg0msb` | control-plane / 운영 서버 |
| 서버 2 | `etri-ser0002-cgnmsb` | worker / 추론 서버 |
| Jetson | `etri-dev0001-jetorn` | edge AI device |
| Raspberry Pi 5 | `etri-dev0002-raspi5` | edge light device |

## 현재 우선순위

1. 서비스 데모 1종을 먼저 완성한다.
2. 디바이스 등록/관리 체계를 정리한다.
3. 디바이스-서비스 바인딩 구조를 구현한다.
4. 통합 대시보드에서 디바이스, 노드, 서비스, 상태, KPI를 함께 보이게 한다.
5. 옥동 시나리오의 생산성 향상 효과를 설명 가능한 지표로 정리한다.
6. 이후 동적 워크플로우, 스케줄링, 가상화, 고도화 오프로딩으로 확장한다.

## 현재 구현 상태

- `state-aggregator`: KubeEdge Device/DeviceStatus, InfluxDB telemetry, Prometheus metric을 통합해 대시보드 상태 API 제공
- `mqttvirtual` mapper 기반 가상 디바이스 PoC
- DeviceModel / Device / DeviceStatus 연동 검증
- Argo CD 기반 `state-aggregator`, `mqttvirtual-mapper`, Redis, NVIDIA device plugin 관리

현재 데모 운영 경로는 `state-aggregator` 중심으로 단순화한다.
과거 워크플로우 실행/배치 실험 컴포넌트는 현행 대시보드와 데모 운영 경로에서 제외한다.

## 디바이스 등록 전략

현재 데모 단계는 사전 등록 방식이다.

1. `DeviceModel`과 `Device` CR을 Kubernetes에 미리 등록한다.
2. 각 Device는 특정 edge node의 `spec.nodeName`에 바인딩한다.
3. mapper는 edgecore/DMI를 통해 해당 Device를 전달받고 정해진 telemetry topic을 구독한다.
4. 실제 센서 수집 프로그램은 Device 이름과 topic 규칙에 맞춰 MQTT payload를 발행한다.

센서가 MQTT로 임의 topic에 publish한다고 자동으로 KubeEdge Device가 생기지는 않는다.
자동 발견과 자동 등록은 후속 `edge-device-agent` 또는 별도 discovery controller로 분리한다.

## 현재 디바이스 배치

- Jetson: `env-device-*`, `vib-device-*`, `act-device-*`, `temp-device-01`
- Raspberry Pi: `rpi-env-device-*`, `rpi-vib-device-*`, `rpi-act-device-*`

테스트 publisher는 실행한 서버의 로컬 mosquitto로 publish한다.
따라서 Jetson에서 실행하면 Jetson에 할당된 디바이스만 live 처리되고, Raspberry Pi 디바이스는 Raspberry Pi에서 publisher를 실행해야 live 처리된다.

## MQTT Topic 규칙

```text
factory/devices/{device-name}/telemetry
factory/devices/{device-name}/command
factory/devices/{device-name}/heartbeat
```

- `telemetry`: 센서 또는 `test_device.py`가 발행하고 mapper가 구독한다.
- `command`: mapper가 명령을 발행하고 테스트 publisher가 구독한다.
- `heartbeat`: 테스트 publisher 보조 heartbeat이며 현재 KubeEdge Device manifest에는 직접 연결하지 않는다.

기본 broker는 각 edge 서버의 로컬 broker다.

```text
tcp://127.0.0.1:1883
```

## 테스트 Publisher

파일:

```text
mappers/script/test_device.py
```

기본 실행:

```bash
python3 mappers/script/test_device.py
```

특정 디바이스:

```bash
DEVICE_FILTER=act-device-06 python3 mappers/script/test_device.py
```

기본 모드는 `SIMULATION_MODE=stable`이다.
act device는 `power=on`, `health=ok`를 유지하고, vib device는 정상 범위 진동값을 발행한다.
장애/랜덤 상태 전이는 명시적으로 켠다.

```bash
SIMULATION_MODE=random ACT_STATE_CHANGE_PROBABILITY=0.15 python3 mappers/script/test_device.py
```
