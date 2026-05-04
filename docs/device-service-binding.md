# Device-Service Binding

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC에서 디바이스와 서비스가 어떤 기준으로 연결되는지 정리한다.

여기서 바인딩은 동적 workflow 배치나 runtime offloading을 의미하지 않는다. 현재 범위의 바인딩은 “어떤 디바이스 데이터와 운영 상태가 어떤 서비스 데모에 사용되고, dashboard에서 그 관계를 어떻게 볼 수 있는가”를 설명하기 위한 운영 관점의 연결 구조다.

## 한 줄 정의

```text
Device -> node -> telemetry / status -> service demo -> dashboard / KPI
```

현재 바인딩의 목적은 다음이다.

- 디바이스가 어떤 node에 배치되어 있는지 보인다.
- 디바이스 telemetry가 어떤 서비스 데모의 입력인지 보인다.
- 서비스가 어떤 device 상태에 의존하는지 보인다.
- dashboard에서 device, service, node, KPI를 함께 해석할 수 있다.

## 바인딩 원칙

현재 PoC에서 디바이스-서비스 바인딩은 다음 조건을 기준으로 본다.

1. KubeEdge `Device` CR이 존재한다.
2. `Device.spec.nodeName`이 실제 edge node에 할당되어 있다.
3. 해당 device의 telemetry 또는 운영 snapshot이 수집된다.
4. 서비스 데모가 해당 device data 또는 상태를 입력으로 사용한다.
5. `state-aggregator`와 dashboard가 이 관계를 운영자가 해석할 수 있는 형태로 보여준다.

바인딩은 다음을 의미하지 않는다.

- runtime workflow scheduling
- dynamic offloading 판단
- placement engine 기반 자동 배치/재배치
- agent-assisted planning 기반 작업 분해
- LLM 기반 전역 제어

## 바인딩 단위

현재 바인딩은 device 단위와 service group 단위로 나눠 설명한다.

### Device 단위

Device 단위 바인딩은 개별 device가 어떤 node와 service에 연결되는지를 나타낸다.

필드 예시:

| 필드 | 의미 |
|---|---|
| `device_name` | KubeEdge Device 이름 |
| `device_type` | env / vib / act / temp / camera 등 device 성격 |
| `nodeName` | device가 할당된 edge node |
| `telemetry_topic` | raw telemetry 입력 topic |
| `command_topic` | command topic |
| `status_properties` | DeviceStatus로 올라오는 운영 snapshot property |
| `telemetry_properties` | InfluxDB data-plane으로 처리되는 raw telemetry property |
| `service_name` | 연결된 서비스 데모 이름 |
| `service_demo_group` | `state-aggregator`가 계산해 API로 내려주는 서비스 데모 그룹 |
| `service_binding_source` | 바인딩 판단 출처. 예: `device_name_pattern`, `event_binding` |
| `service_binding_reason` | 바인딩 판단 이유 |
| `service_role` | service에서 device가 맡는 역할 |
| `dashboard_group` | dashboard에서 보여줄 그룹 |
| `kpi_relation` | KPI 계산에서 device가 기여하는 항목 |

### Service group 단위

Service group 단위 바인딩은 여러 device를 하나의 서비스 데모 관점으로 묶는다.

예시:

```text
설비 상태 모니터링 서비스
  - env-device: 환경 상태 입력
  - vib-device: 설비 진동 상태 입력
  - act-device: 제어/명령 적용 대상
  - state-aggregator: 통합 상태 계산
  - dashboard: 운영 상태와 KPI 표시
```

## 현재 device 계열별 역할

| device 계열 | 주요 데이터 | service 역할 | dashboard 해석 |
|---|---|---|---|
| `env-device-*` | temperature, humidity | 현장 환경 상태 입력 | 환경 상태 freshness와 이상 여부 |
| `vib-device-*` | vibration, rms, peak | 설비 상태/이상 징후 입력 | 진동 상태 freshness와 severity |
| `act-device-*` | power, mode, command_state | 제어/명령 적용 대상 | command 적용 상태와 operational state |
| `temp-device-01` | temperature 계열 값 | 단일 device 연동 확인 | DeviceStatus/telemetry 경로 확인 |
| `rpi-env-device-*` | temperature, humidity | Raspberry Pi edge 환경 입력 | light edge node의 telemetry 상태 |
| `rpi-vib-device-*` | vibration 계열 값 | Raspberry Pi edge 진동 입력 | light edge node의 설비 상태 |
| `rpi-act-device-*` | power, mode, command_state | Raspberry Pi edge 제어 대상 | command loop 상태 |

## 현재 API 바인딩 필드

`state-aggregator`는 device별 서비스 연결 정보를 backend에서 계산한 뒤 `/state/devices`와 `/state/dashboard`의 `devices[]` 항목에 포함한다.

| API field | 의미 |
|---|---|
| `service_connected` | 서비스 데모에 연결된 device인지 여부 |
| `service_demo_group` | dashboard에 표시할 서비스 데모 그룹 |
| `service_binding_source` | 바인딩 판단 출처 |
| `service_binding_reason` | 바인딩 판단 이유 |

현재 기본 판단은 device 이름 패턴을 사용한다.

| device name pattern | `service_demo_group` | `service_binding_reason` |
|---|---|---|
| `vib` 포함 | 설비 상태 모니터링 | device name includes vibration service keyword |
| `act` 포함 | command 상태 확인 | device name includes actuator command service keyword |
| `env` 또는 `temp` 포함 | 환경 상태 모니터링 | device name includes environment service keyword |

이 로직은 dashboard frontend 하드코딩이 아니라 backend의 `DeviceState` 응답 필드로 내려간다. dashboard는 API 응답의 `service_demo_group`과 `service_binding_reason`을 그대로 표시한다.

## node 기준 바인딩

현재 테스트베드의 node 바인딩은 다음과 같다.

| node | 역할 | 연결 device |
|---|---|---|
| `etri-ser0001-cg0msb` | control-plane / 운영 서버 | dashboard, state-aggregator, control-plane component |
| `etri-ser0002-cgnmsb` | worker / 추론 서버 | 서비스 실행 또는 추론 workload 후보 |
| `etri-dev0001-jetorn` | Jetson edge AI device | `env-device-*`, `vib-device-*`, `act-device-*`, `temp-device-01` |
| `etri-dev0002-raspi5` | Raspberry Pi 5 edge device | `rpi-env-device-*`, `rpi-vib-device-*`, `rpi-act-device-*` |

주의:

- Device의 `nodeName`과 publisher 실행 위치가 맞아야 live 경로를 확인할 수 있다.
- Jetson device는 Jetson node local mosquitto로 publish되어야 한다.
- Raspberry Pi device는 Raspberry Pi node local mosquitto로 publish되어야 한다.

## topic 기준 바인딩

각 device는 다음 topic 규칙을 따른다.

```text
factory/devices/{device-name}/telemetry
factory/devices/{device-name}/command
factory/devices/{device-name}/heartbeat
```

| topic | 바인딩 의미 |
|---|---|
| `telemetry` | 서비스 데모가 사용할 raw telemetry 입력 |
| `command` | service/operator가 device 제어 또는 설정 변경에 사용할 명령 경로 |
| `heartbeat` | 테스트 publisher 보조 신호 |

`heartbeat`는 현재 KubeEdge Device manifest에 직접 연결하지 않는다.

## status-plane / data-plane 기준 바인딩

디바이스-서비스 바인딩을 해석할 때 raw telemetry와 운영 snapshot을 구분한다.

| 구분 | 저장/전달 경로 | 서비스에서의 의미 |
|---|---|---|
| raw telemetry data-plane | MQTT -> mapper -> InfluxDB | 분석, 상태 추정, freshness 판단의 입력 |
| DeviceStatus status-plane | mapper -> KubeEdge DeviceStatus | 운영 상태 요약, command 적용 상태, 장애 요약 |

raw telemetry는 DeviceStatus에 직접 올리지 않는다.

## 바인딩 예시

### 예시 1: Jetson 설비 상태 입력

| 항목 | 값 |
|---|---|
| device | `vib-device-01` |
| node | `etri-dev0001-jetorn` |
| telemetry topic | `factory/devices/vib-device-01/telemetry` |
| command topic | `factory/devices/vib-device-01/command` |
| data-plane property | `vibration`, `rms`, `peak` |
| status-plane property | `health`, `severity`, `alarm_latched`, `sampling_interval`, `vibration_status` |
| service role | 설비 진동 상태 입력 |
| dashboard group | 설비 상태 / 진동 상태 |
| KPI relation | telemetry freshness, abnormal signal visibility, operator focus |

### 예시 2: Jetson 제어 대상

| 항목 | 값 |
|---|---|
| device | `act-device-01` |
| node | `etri-dev0001-jetorn` |
| telemetry topic | `factory/devices/act-device-01/telemetry` |
| command topic | `factory/devices/act-device-01/command` |
| data-plane property | command event history, actuation latency 후보 |
| status-plane property | `health`, `power`, `mode`, `sampling_interval`, `command_state` |
| service role | actuator command 적용 대상 |
| dashboard group | 제어 상태 / command 상태 |
| KPI relation | command applied ratio, response visibility |

### 예시 3: Raspberry Pi 환경 상태 입력

| 항목 | 값 |
|---|---|
| device | `rpi-env-device-01` |
| node | `etri-dev0002-raspi5` |
| telemetry topic | `factory/devices/rpi-env-device-01/telemetry` |
| command topic | `factory/devices/rpi-env-device-01/command` |
| data-plane property | `temperature`, `humidity` |
| status-plane property | `health`, `sampling_interval`, `temperature_status`, `humidity_status` |
| service role | light edge 환경 상태 입력 |
| dashboard group | Raspberry Pi edge 상태 |
| KPI relation | mixed-device coverage, telemetry freshness |

## dashboard에서 보여줄 바인딩 정보

dashboard에서는 최소한 다음 관계를 보여줘야 한다.

| 표시 항목 | 의미 |
|---|---|
| device name | 어떤 device인지 |
| node | 어느 edge node에 연결됐는지 |
| device type | env / vib / act 등 device 성격 |
| service group | 어떤 서비스 데모에 묶이는지 |
| telemetry freshness | raw telemetry data-plane이 살아 있는지 |
| DeviceStatus freshness | status-plane snapshot이 최신인지 |
| mapper status | 해당 node의 mapper가 Running인지 |
| overall status | healthy / degraded / unavailable |
| reason | 현재 상태의 운영 해석 |

현재 API에는 `service_connected` 필드가 있으며, 이는 device가 서비스 또는 workflow event와 연결되어 있는지를 나타내는 값으로 사용되고 있다.

현행 연구 방향에서는 이 값을 workflow orchestration 의미로 확장하지 않고, service binding 또는 demo binding 관점으로 해석하는 것이 적절하다.

## 현재 코드 기준 주의점

`edge-orch/state-aggregator/app/models.py`의 `DeviceState`에는 다음 필드가 있다.

```text
service_connected: bool
```

`edge-orch/state-aggregator/app/service.py`에서는 현재 workflow event의 `device_id`, `source_device`, `assigned_node`를 참고해 `service_connected`를 계산한다.

이 방식은 과거 workflow event 구조의 흔적이 남아 있는 형태다. 현재 문서 기준에서는 다음처럼 정리한다.

- `service_connected`는 현재 데모에서 service binding 여부를 나타내는 운영 필드로 해석한다.
- dashboard/API의 service binding KPI는 `service_bound_device_count`, `device_service_binding_ratio` 이름을 사용한다.
- `WorkflowEvent`, `WorkflowState` 등 과거 event 구조 이름은 현행 service binding과 분리해서 해석한다.

## 현재 범위에서 제외하는 바인딩 방식

다음 방식은 현재 디바이스-서비스 바인딩 정의에 포함하지 않는다.

- workflow stage를 기준으로 device를 runtime에 재배치하는 방식
- placement engine이 node/device/service 관계를 자동 변경하는 방식
- cost model이 runtime offloading을 결정하는 방식
- agent-assisted planning layer가 service/device 관계를 생성하는 방식
- LLM 기반 전역 제어가 device-service binding을 수행하는 방식

위 항목은 현재 연구 방향에서 진행하는 다음 단계로 표현하지 않는다. 필요한 경우 과거 검토/실험 또는 archive 경로로만 다룬다.

## 정상 바인딩 판단 기준

현재 데모에서 device-service binding이 정상으로 보이려면 다음 조건을 만족해야 한다.

1. Device CR이 존재한다.
2. Device가 의도한 node에 할당되어 있다.
3. 해당 node의 mapper가 Running이다.
4. publisher가 같은 node의 local mosquitto에 telemetry를 publish한다.
5. InfluxDB에 latest telemetry가 들어온다.
6. DeviceStatus snapshot이 dashboard freshness 기준을 만족한다.
7. dashboard에서 device가 service group 또는 demo group에 표시된다.
8. KPI에서 해당 device가 service visibility 또는 productivity 설명에 기여한다.

## degraded 바인딩 해석

바인딩이 존재하지만 dashboard에서 degraded로 보일 수 있는 경우는 다음이다.

- Device CR은 있지만 telemetry freshness가 없다.
- telemetry는 있지만 DeviceStatus snapshot이 오래됐다.
- mapper는 Running이지만 InfluxDB 적재가 되지 않았다.
- publisher 실행 node와 Device `nodeName`이 다르다.
- service group에는 포함됐지만 KPI 계산에 필요한 signal이 부족하다.
- command topic은 있으나 command 적용 상태가 DeviceStatus에 반영되지 않았다.

이 경우는 service binding 자체가 무조건 실패했다는 뜻이 아니다. 운영 가시화에 필요한 최신 signal이 부족한 상태로 해석한다.

## 관련 문서

- `docs/current-demo-path.md`: 현재 device/MQTT/mapper/state-aggregator/dashboard 연결 경로
- `docs/device-status-policy.md`: DeviceStatus와 raw telemetry 분리 정책
- `docs/dashboard-policy.md`: dashboard 상태 판단 기준
- `docs/scope.md`: 현재 범위와 제외 범위
- `docs/repo-structure.md`: 레포 디렉터리 역할 분류
