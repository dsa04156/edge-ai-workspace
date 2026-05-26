# Current Demo Path

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC에서 디바이스, MQTT, mapper, telemetry 저장소, 상태 통합 API, dashboard가 어떤 경로로 연결되는지 정리한다.

이 경로는 전체 PoC를 구성하는 구현 과정 중 하나다. 목적은 디바이스와 서비스를 실제로 연결하고, 그 상태를 dashboard에서 운영 관점으로 확인할 수 있게 만드는 것이다.

## 한 줄 요약

```text
physical / virtual device
  -> MQTT command/status topic
  -> mqttvirtual mapper / MapperFramework DMI adapter
  -> KubeEdge DeviceStatus summary / command path
  -> state-aggregator
  -> dashboard / service demo view

raw telemetry ingestion (future)
  -> EdgeX Device Service / EdgeX MessageBus
  -> telemetry store / analytics consumers
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

4. telemetry ingestion plane
   - raw telemetry는 DeviceStatus에 직접 올리지 않는다.
   - MapperFramework를 raw telemetry export engine으로 확장하지 않는다.
   - 향후 raw telemetry ingestion은 EdgeX 기반 별도 plane에서 처리한다.

5. status/control-plane
   - `DeviceStatus`는 저빈도 운영 snapshot으로 사용한다.
   - health, severity, command_state, online/offline, control_response 같은 운영 상태를 중심으로 둔다.

6. 상태 통합 계층
   - `state-aggregator`가 Kubernetes, KubeEdge, InfluxDB, Prometheus, mapper 상태를 함께 읽는다.
   - dashboard가 사용할 device/node/service 상태와 KPI를 만든다.

7. dashboard 계층
   - dashboard는 단순히 Device CR 존재 여부만 보지 않는다.
   - dashboard는 InfluxDB latest telemetry freshness를 `available` 판단의 1차 기준으로 보며, DeviceStatus freshness는 status-plane 관찰용 보조 신호로 별도 표시한다. mapper 상태와 node 상태는 선행 조건으로 함께 확인한다.

8. workflow designer 계층
   - `edge-orch/workflow-designer/`는 서비스가 어떤 device를 입력으로 쓰고, 어떤 stage 흐름으로 구성되며, 각 stage가 어떤 node에 배치되는지 dry-run으로 설계/시각화한다.
   - 이 도구는 read-only + dry-run plan generation 전용이다. workflow/offloading/placement 자동 실행, Kubernetes 배포, MQTT command publish, Device CR 수정은 수행하지 않는다.

## 구성 요소

| 구분 | 경로/컴포넌트 | 역할 |
|---|---|---|
| Device 정의 | `edge-device/` | `DeviceModel` / `Device` manifest 생성과 관리 |
| 테스트 publisher | `mappers/script/test_device.py` | MQTT telemetry / command 테스트 입력 생성 |
| mapper | `mappers/mqttvirtual/` | MQTT topic 구독, command publish, KubeEdge DMI 연동, DeviceStatus/Twin reported 처리 |
| telemetry ingestion | EdgeX plane TODO | raw telemetry ingestion, 저장, graph/anomaly 분석은 MapperFramework 주 경로에서 분리 |
| 상태 통합 | `edge-orch/state-aggregator/` | KubeEdge / InfluxDB / Prometheus 상태 통합 API |
| dashboard | `edge-orch/state-aggregator/app/static/` | 디바이스, 노드, 서비스, KPI 운영 가시화 |
| workflow designer | `edge-orch/workflow-designer/` | 서비스 stage, input device, target node를 dry-run으로 시각화하고 execution plan을 생성 |

## Device / DeviceModel

현재 데모 단계에서는 KubeEdge `DeviceModel`과 `Device`를 사전에 등록한다.

센서가 MQTT topic에 임의로 publish한다고 KubeEdge `Device`가 자동으로 생성되는 구조가 아니다. 먼저 `DeviceModel`과 `Device`가 Kubernetes에 등록되어 있어야 하고, mapper는 edgecore/DMI를 통해 자신이 처리할 Device 정보를 전달받는다.

현재 기준 node 할당은 다음 규칙을 따른다.

| 디바이스 계열 | 할당 node |
|---|---|
| Jetson 계열 device | `etri-dev0001-jetorn` |
| Raspberry Pi 계열 device | `etri-dev0002-raspi5` |

현재 dashboard 기준 등록 device는 다음 4개 Arduino 센서다.

- `env-arduino-temperature-01`
- `env-arduino-light-01`
- `env-arduino-magnetic-01`
- `vib-arduino-acceleration-01`

현재 4개 device는 `etri-dev0001-jetorn`에 할당되어 있다. Jetson 디바이스는 `etri-dev0001-jetorn`, Raspberry Pi 디바이스는 `etri-dev0002-raspi5`에 할당하는 규칙은 유지한다.

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
- raw telemetry stream은 DeviceStatus가 아니라 향후 EdgeX telemetry ingestion plane에서 처리한다.

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
7. raw telemetry 영구 저장은 MapperFramework 주 경로에서 제외하고 향후 EdgeX ingestion plane으로 분리한다.

현재 deployment 기준에서 mapper는 edge node에서 동작하며, `/etc/kubeedge/dmi.sock`을 통해 edgecore/DMI와 연결된다.

## DeviceStatus snapshot

`DeviceStatus`는 고빈도 telemetry 저장 경로가 아니다.

현재 정책은 다음이다.

- `DeviceStatus`는 control/status-plane의 저빈도 운영 snapshot으로 제한한다.
- raw telemetry는 DeviceStatus에 올리지 않는다.
- raw telemetry는 향후 EdgeX telemetry ingestion plane으로 처리한다.
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
- `online` / `offline`
- `control_response`
- `last_control_response`
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
- `acceleration_x`, `acceleration_y`, `acceleration_z`
- `x`, `y`, `z`
- `rms`
- `peak`
- `raw_samples`
- `waveform`
- image / frame
- every-event log
- inference result stream

## EdgeX telemetry ingestion plane TODO

향후 raw telemetry ingestion은 EdgeX 기반 별도 plane으로 구성한다.
MapperFramework는 이 경로의 export engine이 아니다.

TODO: EdgeX Device Profile과 KubeEdge DeviceModel 간 매핑표를 문서화한다.

예시 분리 기준:

| device 계열 | DeviceStatus summary | EdgeX raw telemetry 후보 |
|---|---|---|
| env device | `health`, `sampling_interval`, `temperature_status`, `humidity_status` | `temperature`, `humidity` |
| vib device | `health`, `severity`, `alarm_latched`, `sampling_interval`, `vibration_status` | `vibration`, `rms`, `peak`, raw vibration samples |
| act/rpi-act device | `health`, `power`, `mode`, `sampling_interval`, `command_state`, `reported_config_version`, `control_response` | actuation event history, state transition history |

EdgeX plane이 붙기 전까지 raw telemetry freshness KPI는 전환 대상 지표로 취급한다. DeviceStatus freshness는 status-plane snapshot 최신성으로 별도 유지한다.

## state-aggregator

`state-aggregator`는 dashboard 상태 API를 제공하는 FastAPI 기반 컴포넌트다.

관련 경로:

```text
edge-orch/state-aggregator/
```

API는 현재 데모 핵심 API와 legacy/compatibility API로 구분한다.

현재 데모 핵심 API:

```text
GET /state/nodes
GET /state/devices
GET /state/dashboard
GET /state/summary
GET /state/operator-assistant
GET /metrics
```

| API | 용도 |
|---|---|
| `GET /state/nodes` | Kubernetes / Prometheus 기반 node 상태 조회 |
| `GET /state/devices` | KubeEdge Device / DeviceStatus / mapper / telemetry freshness 통합 조회 |
| `GET /state/dashboard` | dashboard용 요약 상태와 KPI 조회 |
| `GET /state/summary` | 전체 운영 상태 요약 조회 |
| `GET /state/operator-assistant` | 운영자 보조 요약과 우선 점검 대상 조회 |
| `GET /metrics` | Prometheus scrape용 metric 노출 |

Legacy/compatibility API:

```text
GET /state/cost-model
POST /workflow-event
GET /state/workflows
```

위 legacy/compatibility API는 과거 workflow/placement/cost-model 실험 호환용이다. 현재 데모 핵심 경로가 아니며, workflow/offloading/placement/autonomous agent 제어를 현재 구현 기능처럼 설명하지 않는다.

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
- `status.state=online`만으로 `available` 판단하지 않는다.
- DeviceStatus snapshot freshness와 DB latest timestamp freshness를 분리해서 본다.
- mapper pod가 Running인지 확인한다.
- device가 할당된 node가 dashboard 기준 `node_ready`인지 확인한다. 이 값은 Kubernetes `Ready`가 아니라 Prometheus/node-exporter 기반 `node_health != unavailable` 판단이다.
- Kubernetes node Ready는 `kubectl get nodes`로 별도 확인한다.
- telemetry-enabled device는 InfluxDB device-level latest timestamp를 `available` 판단의 1차 기준으로 확인한다.

기본 freshness 설정은 다음이다.

```bash
DEVICE_STATUS_FRESH_SECONDS=90
TELEMETRY_FRESH_SECONDS=90
MAPPER_HEARTBEAT_FRESH_SECONDS=60
```

상태 판단 의미는 다음처럼 정리한다.

| 상태 | 의미 |
|---|---|
| `healthy` | node/mapper가 정상이고 InfluxDB latest telemetry가 dashboard freshness 기준을 만족하는 상태 (DeviceStatus freshness는 별도 표기되는 보조 신호) |
| `degraded` | 등록 또는 일부 경로는 있으나 fresh signal이 부족하거나 일부 상태가 오래된 상태 |
| `unavailable` | node 미할당, node unavailable, mapper 미동작, 명시 offline 등 운영 경로가 끊긴 상태 |

## Jetson 경로

Jetson device는 `etri-dev0001-jetorn`에 할당한다.

대표 device:

```text
env-arduino-temperature-01
env-arduino-light-01
env-arduino-magnetic-01
vib-arduino-acceleration-01
```

Jetson 경로 점검 흐름은 다음이다.

1. Jetson node가 Kubernetes/KubeEdge에서 Ready 상태인지 확인한다.
2. Jetson에 할당된 Device CR이 존재하는지 확인한다.
3. Jetson node에서 `mqttvirtual` mapper가 Running인지 확인한다.
4. Jetson node의 local mosquitto에 publisher가 telemetry를 발행하는지 확인한다.
5. InfluxDB에 해당 device의 latest telemetry가 들어오는지 확인한다.
6. DeviceStatus snapshot이 fresh한지 별도 확인한다. 단 telemetry가 fresh하면 DeviceStatus가 stale이어도 healthy일 수 있다.
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
| telemetry ingestion plane | raw telemetry 저장/조회 | EdgeX TODO: `temperature`, `humidity`, `vibration`, `acceleration_x/y/z`, `waveform` |
| status-plane | 저빈도 운영 snapshot | `health`, `severity`, `command_state`, `online/offline`, `control_response` |

정책:

- raw telemetry는 MapperFramework 주 경로가 아니라 EdgeX telemetry ingestion plane으로 분리한다.
- DeviceStatus는 운영 상태 요약으로 제한한다.
- dashboard는 두 경로의 freshness를 분리해서 판단한다.

이 분리는 DeviceStatus가 고빈도 telemetry stream으로 과부하되는 것을 막고, dashboard가 운영 상태와 raw telemetry 상태를 별도로 설명할 수 있게 한다.

## degraded 상태가 나오는 대표 원인

현재 데모에서 device가 `degraded`로 보일 수 있는 대표 원인은 다음이다.

1. Device는 등록되어 있지만 live status가 unknown인 경우
2. mapper는 Running이지만 DeviceStatus summary가 fresh하지 않은 경우
3. EdgeX telemetry plane 전환 전 호환 telemetry freshness 지표가 stale인 경우
4. publisher가 실행되지 않았거나 잘못된 node에서 실행된 경우
5. publisher가 local mosquitto `127.0.0.1:1883`이 아닌 다른 broker로 publish한 경우
6. Device는 Jetson에 할당됐지만 Raspberry Pi에서 publisher를 실행한 경우 또는 그 반대의 경우
7. raw telemetry는 들어오지만 DeviceStatus report 대상 summary property가 갱신되지 않는 경우
8. node 또는 mapper 상태가 dashboard 판단 기준과 맞지 않는 경우

`degraded`는 반드시 시스템 전체 실패를 의미하지 않는다.

현재 기준에서는 “등록, mapper, API 경로 중 일부는 존재하지만 InfluxDB latest telemetry가 없거나 stale인 상태”를 우선 `degraded`로 해석한다. DeviceStatus summary freshness는 status-plane 보조 신호로 별도 표시한다.

dashboard KPI는 `telemetry_device_count`/`device_telemetry_ratio`(telemetry configured 범위), `fresh_telemetry_device_count`/`telemetry_freshness_ratio`(실제 최신 telemetry), `fresh_device_status_count`/`device_status_freshness_ratio`(DeviceStatus 최신성), `operator_focus_count`(degraded/unavailable device + non-healthy node, workflow risk 제외)로 구분해서 읽는다.

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

## Workflow Designer에서 보는 현재 데모 경로

Workflow Designer는 이 경로를 하나의 node-column 화면으로 합치지 않고 다음 3개 관점으로 나누어 본다.

1. Service Workflow DAG
   - input device에서 시작해 `collect -> preprocess/normalize -> inference/rule-check -> event-publish -> sink`로 이어지는 서비스 논리 흐름을 표시한다.
   - `raw-signal`, `feature-vector`, `mqtt-event`, `environment-state` 같은 output data 이름은 stage 사이 edge label로 표시한다.

2. Stage Placement
   - 각 stage가 `factoryName-ser0001-CG0MS0`, `etri-dev0001-jetorn`, `etri-dev0002-raspi5` 중 어디서 실행되는지 별도 표/카드로 표시한다.
   - target node 변경은 이 dry-run placement view에서만 수행한다.

3. Data Transport / Endpoint
   - output data가 어떤 transport로 어느 consumer stage 또는 platform endpoint에 전달되는지 표시한다.
   - platform endpoint는 compute node와 분리하며 `MQTT Broker`, `InfluxDB`, `State Aggregator`, `Dashboard`로 구분한다.

이 기능은 read-only + dry-run 설계 도구이며 실제 배포, MQTT command publish, Device CR 수정, runtime migration/offloading을 수행하지 않는다.

