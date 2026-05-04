# Current Demo Path

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC에서 디바이스, MQTT, mapper, telemetry 저장소, 상태 통합 API, dashboard가 어떤 경로로 연결되는지 정리한다.

이 경로는 전체 PoC를 구성하는 구현 과정 중 하나다. 목적은 디바이스와 서비스를 실제로 연결하고, 그 상태를 dashboard에서 운영 관점으로 확인할 수 있게 만드는 것이다.

## 한 줄 요약

```text
physical / virtual device
  -> MQTT telemetry / command topic
  -> mqttvirtual mapper
  -> KubeEdge DeviceStatus snapshot
  -> InfluxDB raw telemetry data-plane
  -> state-aggregator
  -> dashboard / service demo view
```

## 전체 흐름

현재 데모 경로는 다음 계층으로 나뉜다.

1. Device 정의 계층
   - KubeEdge `DeviceModel`과 `Device`를 사전에 등록한다.
   - 각 `Device`는 Jetson 또는 Raspberry Pi edge node에 할당된다.

2. Device data 입력 계층
   - 실제 센서 또는 테스트 publisher가 MQTT topic으로 telemetry를 발행한다.
   - command topic을 통해 설정 변경 또는 제어 명령을 받을 수 있다.

3. mapper 계층
   - `mqttvirtual` mapper가 MQTT broker에 연결한다.
   - mapper는 telemetry topic을 구독하고 command topic으로 명령을 발행한다.
   - KubeEdge DMI를 통해 `Device` / `DeviceStatus` 계층과 연결된다.

4. telemetry data-plane
   - raw telemetry는 DeviceStatus에 직접 올리지 않는다.
   - raw telemetry는 MQTT / InfluxDB 경로를 통해 data-plane에서 처리한다.

5. status/control-plane
   - `DeviceStatus`는 저빈도 운영 snapshot으로 사용한다.
   - health, severity, alarm, power, mode, sampling_interval 같은 운영 상태를 중심으로 둔다.

6. 상태 통합 계층
   - `state-aggregator`가 Kubernetes, KubeEdge, InfluxDB, Prometheus, mapper 상태를 함께 읽는다.
   - dashboard가 사용할 device/node/service 상태와 KPI를 만든다.

7. dashboard 계층
   - dashboard는 단순히 Device CR 존재 여부만 보지 않는다.
   - telemetry freshness, DeviceStatus freshness, mapper 상태, node 상태를 함께 보고 healthy/degraded/unavailable을 판단한다.

## 구성 요소

| 구분 | 경로/컴포넌트 | 역할 |
|---|---|---|
| Device 정의 | `edge-device/` | `DeviceModel` / `Device` manifest 생성과 관리 |
| 테스트 publisher | `mappers/script/test_device.py` | MQTT telemetry / command 테스트 입력 생성 |
| mapper | `mappers/mqttvirtual/` | MQTT topic 구독, command publish, KubeEdge DMI 연동 |
| telemetry 저장 | `influxdb/` | raw telemetry data-plane 저장소 |
| 상태 통합 | `edge-orch/state-aggregator/` | KubeEdge / InfluxDB / Prometheus 상태 통합 API |
| dashboard | `edge-orch/state-aggregator/app/static/` | 디바이스, 노드, 서비스, KPI 운영 가시화 |

## Device / DeviceModel

현재 데모 단계에서는 KubeEdge `DeviceModel`과 `Device`를 사전에 등록한다.

센서가 MQTT topic에 임의로 publish한다고 KubeEdge `Device`가 자동으로 생성되는 구조가 아니다. 먼저 `DeviceModel`과 `Device`가 Kubernetes에 등록되어 있어야 하고, mapper는 edgecore/DMI를 통해 자신이 처리할 Device 정보를 전달받는다.

현재 기준 node 할당은 다음 규칙을 따른다.

| 디바이스 계열 | 할당 node |
|---|---|
| Jetson 계열 device | `etri-dev0001-jetorn` |
| Raspberry Pi 계열 device | `etri-dev0002-raspi5` |

현재 배치 기준은 다음과 같다.

- Jetson: `env-device-*`, `vib-device-*`, `act-device-*`, `temp-device-01`
- Raspberry Pi: `rpi-env-device-*`, `rpi-vib-device-*`, `rpi-act-device-*`

관련 경로:

```text
edge-device/models/
edge-device/devices.yaml
edge-device/scripts/generate_devices.py
```

## MQTT topic

현재 MQTT topic 규칙은 다음과 같다.

```text
factory/devices/{device-name}/telemetry
factory/devices/{device-name}/command
factory/devices/{device-name}/heartbeat
```

각 topic의 의미는 다음이다.

| topic | 역할 |
|---|---|
| `factory/devices/{device-name}/telemetry` | 센서 또는 테스트 publisher가 raw telemetry를 발행하는 입력 topic |
| `factory/devices/{device-name}/command` | mapper가 명령을 발행하고 publisher가 구독하는 command topic |
| `factory/devices/{device-name}/heartbeat` | 테스트 publisher 보조 heartbeat topic |

주의할 점:

- `heartbeat`는 테스트 publisher 보조 신호다.
- 현재 KubeEdge `Device` manifest에는 `heartbeat`를 직접 연결하지 않는다.
- raw telemetry stream은 DeviceStatus가 아니라 InfluxDB data-plane으로 처리한다.

## 테스트 publisher

테스트 publisher는 다음 파일이다.

```text
mappers/script/test_device.py
```

publisher는 실행한 서버의 local mosquitto로 publish한다.

```text
tcp://127.0.0.1:1883
```

따라서 Jetson에서 publisher를 실행하면 Jetson에 할당된 device가 live 처리되는 경로를 확인할 수 있고, Raspberry Pi device는 Raspberry Pi에서 publisher를 실행해야 live 경로를 확인할 수 있다.

대표 실행 예시는 다음과 같다.

```bash
python3 mappers/script/test_device.py
```

특정 device만 테스트할 때는 `DEVICE_FILTER`를 사용할 수 있다.

```bash
DEVICE_FILTER=act-device-06 python3 mappers/script/test_device.py
```

device plan을 나눠 실행할 때는 다음 환경변수를 사용한다.

```bash
DEVICE_PLAN=jetson python3 mappers/script/test_device.py
DEVICE_PLAN=rpi python3 mappers/script/test_device.py
DEVICE_PLAN=all python3 mappers/script/test_device.py
```

기본 simulation mode는 stable 기준으로 둔다.

```bash
SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

장애 또는 상태 변화 시나리오가 필요할 때만 random mode를 명시적으로 사용한다.

```bash
SIMULATION_MODE=random ACT_STATE_CHANGE_PROBABILITY=0.15 python3 mappers/script/test_device.py
```

## mqttvirtual mapper

`mqttvirtual` mapper는 MQTT 기반 device data를 KubeEdge device 계층과 연결한다.

관련 경로:

```text
mappers/mqttvirtual/
mappers/mqttvirtual/driver/driver.go
mappers/mqttvirtual/device/devicestatus.go
mappers/mqttvirtual/resource/deployment.yaml
mappers/mqttvirtual/resource/configmap.yaml
```

mapper의 역할은 다음이다.

1. MQTT broker에 연결한다.
2. `factory/devices/{device-name}/telemetry` topic을 구독한다.
3. 수신한 payload의 최신 값을 mapper 내부 cache에 유지한다.
4. KubeEdge DMI를 통해 device property read/write 경로를 제공한다.
5. `factory/devices/{device-name}/command` topic으로 command를 publish한다.
6. 허용된 운영 상태 property만 DeviceStatus report 대상으로 다룬다.

현재 deployment 기준에서 mapper는 edge node에서 동작하며, `/etc/kubeedge/dmi.sock`을 통해 edgecore/DMI와 연결된다.

## DeviceStatus snapshot

`DeviceStatus`는 고빈도 telemetry 저장 경로가 아니다.

현재 정책은 다음이다.

- `DeviceStatus`는 control/status-plane의 저빈도 운영 snapshot으로 제한한다.
- raw telemetry는 DeviceStatus에 올리지 않는다.
- raw telemetry는 MQTT / InfluxDB data-plane으로 처리한다.
- `ReportDeviceStates`는 기본적으로 비활성화한다.

기본 정책:

```bash
DEVICE_STATES_REPORT_ENABLED=false
```

DeviceStatus에 올릴 수 있는 값은 운영 상태 요약이다.

예시:

- `health`
- `severity`
- `alarm_latched`
- `power`
- `mode`
- `sampling_interval`
- `config_version`
- `reported_config_version`
- `command_state`
- `last_error_code`
- `last_error_message`
- `temperature_status`
- `humidity_status`
- `vibration_status`

DeviceStatus에 올리지 않는 값은 raw stream 성격의 값이다.

예시:

- `temperature` raw stream
- `humidity` raw stream
- `vibration` raw stream
- `rms`
- `peak`
- `raw_samples`
- `waveform`
- image / frame
- every-event log
- inference result stream

## InfluxDB telemetry data-plane

InfluxDB는 raw telemetry data-plane 저장소로 사용한다.

Device manifest에서 raw telemetry property는 KubeEdge mapper framework의 `pushMethod.dbMethod.influxdb2` 경로를 사용한다.

예시 분리 기준:

| device 계열 | DeviceStatus | InfluxDB data-plane |
|---|---|---|
| env device | `health`, `sampling_interval`, `temperature_status`, `humidity_status` | `temperature`, `humidity` |
| vib device | `health`, `severity`, `alarm_latched`, `sampling_interval`, `vibration_status` | `vibration`, `rms`, `peak`, raw vibration samples |
| act device | `health`, `power`, `mode`, `sampling_interval`, `command_state`, `reported_config_version` | command event history, actuation latency, state transition history |

현재 dashboard는 InfluxDB latest telemetry timestamp를 보고 raw telemetry data-plane이 살아 있는지 판단한다.

## state-aggregator

`state-aggregator`는 dashboard 상태 API를 제공하는 FastAPI 기반 컴포넌트다.

관련 경로:

```text
edge-orch/state-aggregator/
```

주요 API는 다음이다.

```text
GET /state/nodes
GET /state/devices
GET /state/dashboard
GET /state/summary
GET /state/cost-model
POST /workflow-event
GET /metrics
```

현재 데모 경로에서 중요한 API는 다음이다.

| API | 용도 |
|---|---|
| `GET /state/nodes` | Kubernetes / Prometheus 기반 node 상태 조회 |
| `GET /state/devices` | KubeEdge Device / DeviceStatus / mapper / telemetry freshness 통합 조회 |
| `GET /state/dashboard` | dashboard용 요약 상태와 KPI 조회 |
| `GET /state/summary` | 전체 운영 상태 요약 조회 |
| `GET /metrics` | Prometheus scrape용 metric 노출 |

`state-aggregator`가 통합하는 입력은 다음이다.

- Kubernetes node 상태
- KubeEdge `Device` 목록
- KubeEdge `DeviceStatus` snapshot
- `mqttvirtual` mapper pod Running 여부
- InfluxDB latest telemetry timestamp
- Prometheus node metric

## dashboard

dashboard는 `state-aggregator` API를 기반으로 운영 상태를 보여준다.

현재 dashboard 판단 기준은 다음과 같다.

- Device CR이 존재한다고 healthy가 되는 것은 아니다.
- `status.state=online`만으로 healthy 판단하지 않는다.
- DeviceStatus snapshot freshness와 raw telemetry freshness를 분리해서 본다.
- mapper pod가 Running인지 확인한다.
- device가 할당된 node가 Ready인지 확인한다.
- telemetry가 있는 device는 InfluxDB latest timestamp를 확인한다.

기본 freshness 설정은 다음이다.

```bash
DEVICE_STATUS_FRESH_SECONDS=90
TELEMETRY_FRESH_SECONDS=90
MAPPER_HEARTBEAT_FRESH_SECONDS=60
```

상태 판단 의미는 다음처럼 정리한다.

| 상태 | 의미 |
|---|---|
| `healthy` | node/mapper가 정상이고 DeviceStatus와 telemetry freshness가 dashboard 기준을 만족하는 상태 |
| `degraded` | 등록 또는 일부 경로는 있으나 fresh signal이 부족하거나 일부 상태가 오래된 상태 |
| `unavailable` | node 미할당, node unavailable, mapper 미동작, 명시 offline 등 운영 경로가 끊긴 상태 |

## Jetson 경로

Jetson device는 `etri-dev0001-jetorn`에 할당한다.

대표 device 계열:

```text
env-device-*
vib-device-*
act-device-*
temp-device-01
```

Jetson 경로 점검 흐름은 다음이다.

1. Jetson node가 Kubernetes/KubeEdge에서 Ready 상태인지 확인한다.
2. Jetson에 할당된 Device CR이 존재하는지 확인한다.
3. Jetson node에서 `mqttvirtual` mapper가 Running인지 확인한다.
4. Jetson node의 local mosquitto에 publisher가 telemetry를 발행하는지 확인한다.
5. InfluxDB에 해당 device의 latest telemetry가 들어오는지 확인한다.
6. DeviceStatus snapshot이 fresh한지 확인한다.
7. `/state/devices` 또는 dashboard에서 overall status를 확인한다.

## Raspberry Pi 경로

Raspberry Pi device는 `etri-dev0002-raspi5`에 할당한다.

대표 device 계열:

```text
rpi-env-device-*
rpi-vib-device-*
rpi-act-device-*
```

Raspberry Pi 경로 점검 흐름은 Jetson과 동일하지만, publisher 실행 위치가 중요하다.

Raspberry Pi device를 live로 만들려면 Raspberry Pi node의 local mosquitto에 telemetry가 publish되어야 한다.

## data-plane / status-plane 분리

현재 데모 경로에서 핵심적으로 지켜야 할 경계는 data-plane과 status-plane의 분리다.

| 구분 | 역할 | 예시 |
|---|---|---|
| data-plane | raw telemetry 저장/조회 | `temperature`, `humidity`, `vibration`, `rms`, `peak`, raw samples |
| status-plane | 저빈도 운영 snapshot | `health`, `severity`, `power`, `mode`, `sampling_interval`, `command_state` |

정책:

- raw telemetry는 MQTT / InfluxDB data-plane에 둔다.
- DeviceStatus는 운영 상태 요약으로 제한한다.
- dashboard는 두 경로의 freshness를 분리해서 판단한다.

이 분리는 DeviceStatus가 고빈도 telemetry stream으로 과부하되는 것을 막고, dashboard가 운영 상태와 raw telemetry 상태를 별도로 설명할 수 있게 한다.

## degraded 상태가 나오는 대표 원인

현재 데모에서 device가 `degraded`로 보일 수 있는 대표 원인은 다음이다.

1. Device는 등록되어 있지만 live status가 unknown인 경우
2. mapper는 Running이지만 InfluxDB에 fresh telemetry가 없는 경우
3. DeviceStatus snapshot timestamp가 오래된 경우
4. publisher가 실행되지 않았거나 잘못된 node에서 실행된 경우
5. publisher가 local mosquitto `127.0.0.1:1883`이 아닌 다른 broker로 publish한 경우
6. Device는 Jetson에 할당됐지만 Raspberry Pi에서 publisher를 실행한 경우 또는 그 반대의 경우
7. raw telemetry는 들어오지만 DeviceStatus report 대상 property가 갱신되지 않는 경우
8. node 또는 mapper 상태가 dashboard 판단 기준과 맞지 않는 경우

`degraded`는 반드시 시스템 전체 실패를 의미하지 않는다.

현재 기준에서는 “등록, mapper, API 경로 중 일부는 존재하지만 dashboard가 healthy로 판단하기 위한 fresh telemetry 또는 fresh DeviceStatus snapshot이 부족한 상태”로 해석한다.

## 현재 데모 경로에서 제외하는 것

다음 항목은 현재 데모 경로에 포함하지 않는다.

- `edge-orch/workflow_executor/` 중심 동적 workflow 실행
- `edge-orch/workflow_reporter/` 중심 stage event pipeline
- `edge-orch/placement_engine/` 중심 자동 배치/재배치
- cost model 기반 runtime offloading 판단
- agent-assisted planning layer
- LLM 기반 전역 제어 구조
- 전체 플랫폼을 자율 제어 대상으로 두는 orchestration 구조

위 항목은 현재 연구 방향에서 진행하는 다음 단계로 표현하지 않는다. 필요한 경우 과거 검토/실험 자료 또는 보관 경로로만 다룬다.

## 관련 문서

- `docs/scope.md`: 현재 PoC 범위와 제외 범위
- `docs/repo-structure.md`: 레포 디렉터리 역할 분류
- `docs/project-context.md`: 프로젝트 배경과 테스트베드 기준
- `docs/device-status-policy.md`: DeviceStatus와 raw telemetry 분리 정책
- `docs/dashboard-policy.md`: dashboard 상태 판단 기준
- `docs/roadmap.md`: 현재 산출물과 단계별 작업 방향
