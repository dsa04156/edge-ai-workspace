# Service Demo Scenario

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC에서 우선 보여줄 서비스 데모 시나리오를 정리한다.

현재 단계의 목적은 복잡한 동적 orchestration을 증명하는 것이 아니라, 디바이스와 서비스를 실제로 연결하고 dashboard에서 운영자가 상태와 생산성 향상 효과를 설명할 수 있게 만드는 것이다.

## 대표 시나리오

대표 서비스 데모는 다음으로 둔다.

```text
혼합 디바이스 기반 설비 상태 모니터링 및 이상 징후 가시화 서비스
```

이 시나리오는 Jetson, Raspberry Pi, x86 서버가 함께 있는 환경에서 환경 센서, 진동 센서, actuator 상태를 수집하고, 이를 dashboard에서 서비스 단위로 묶어 보여주는 데 초점을 둔다.

## 현장 문제

실공장 또는 현장 PoC에서 운영자가 겪는 문제는 다음처럼 정리한다.

1. 여러 종류의 edge device가 각기 다른 node에 흩어져 있다.
2. device가 등록되어 있어도 실제 telemetry가 살아 있는지 바로 알기 어렵다.
3. raw telemetry, 운영 상태, node 상태, service 상태가 분리되어 있어 현장 상태를 한눈에 보기 어렵다.
4. 이상 징후가 발생했을 때 어떤 device와 service가 영향을 받는지 추적하기 어렵다.
5. 운영자가 수동으로 여러 명령과 로그를 확인해야 해 대응 시간이 길어진다.

현재 데모는 이 문제를 다음 방식으로 줄이는 것을 보여준다.

- device와 service의 연결 관계를 dashboard에서 보이게 한다.
- telemetry freshness와 DeviceStatus freshness를 분리해서 보여준다.
- node, mapper, device 상태를 함께 해석한다.
- operator focus 또는 issue list를 통해 우선 확인 대상을 줄인다.
- KPI로 현장 적용성과 생산성 향상 효과를 설명한다.

## 데모 목표

이번 서비스 데모에서 보여줄 목표는 다음이다.

1. Jetson과 Raspberry Pi에 할당된 device가 사전 등록되어 있음을 보인다.
2. 각 device가 정해진 MQTT topic으로 telemetry를 발행하는 것을 보인다.
3. `mqttvirtual` mapper가 telemetry/command 경로를 연결하는 것을 보인다.
4. raw telemetry가 InfluxDB data-plane으로 처리되는 것을 보인다.
5. DeviceStatus는 저빈도 운영 snapshot으로만 사용되는 것을 보인다.
6. `state-aggregator`가 device, node, mapper, telemetry 상태를 통합하는 것을 보인다.
7. dashboard에서 device-service binding과 KPI를 운영 관점으로 보여준다.

## 시나리오 구성

| 구분 | 구성 요소 | 역할 |
|---|---|---|
| control-plane / 운영 서버 | `etri-ser0001-cg0msb` | Kubernetes control-plane, dashboard/API 운영 |
| worker / 추론 서버 | `etri-ser0002-cgnmsb` | 서비스 실행 또는 추론 workload 후보 |
| Jetson edge AI device | `etri-dev0001-jetorn` | Jetson 계열 device telemetry 입력 |
| Raspberry Pi edge device | `etri-dev0002-raspi5` | light edge 계열 device telemetry 입력 |
| mapper | `mappers/mqttvirtual/` | MQTT와 KubeEdge device 계층 연결 |
| state API | `edge-orch/state-aggregator/` | 통합 상태 API 제공 |
| dashboard | `edge-orch/state-aggregator/app/static/` | 운영 가시화 |
| telemetry store | InfluxDB | raw telemetry 저장 및 latest 조회 |

## 사용 device

### Jetson 계열

| device | 역할 | 서비스 의미 |
|---|---|---|
| `env-device-*` | 온도/습도 등 환경 상태 입력 | 현장 환경 조건 확인 |
| `vib-device-*` | 진동 상태 입력 | 설비 이상 징후 확인 |
| `act-device-*` | actuator 상태/명령 대상 | 제어 상태와 command 적용 확인 |
| `temp-device-01` | 단일 온도 device | DeviceStatus/telemetry 연동 확인 |

### Raspberry Pi 계열

| device | 역할 | 서비스 의미 |
|---|---|---|
| `rpi-env-device-*` | light edge 환경 상태 입력 | Raspberry Pi edge node의 환경 상태 확인 |
| `rpi-vib-device-*` | light edge 진동 상태 입력 | Raspberry Pi edge node의 설비 상태 확인 |
| `rpi-act-device-*` | light edge 제어 대상 | Raspberry Pi edge command loop 확인 |

## 데이터 흐름

서비스 데모의 기본 데이터 흐름은 다음이다.

```text
sensor / test publisher
  -> factory/devices/{device-name}/telemetry
  -> mqttvirtual mapper
  -> InfluxDB raw telemetry data-plane
  -> state-aggregator latest telemetry query
  -> dashboard service demo view
```

운영 상태 snapshot 흐름은 다음이다.

```text
mqttvirtual mapper
  -> KubeEdge DeviceStatus
  -> state-aggregator DeviceStatus freshness 판단
  -> dashboard status panel
```

command 흐름은 다음이다.

```text
operator / service action
  -> factory/devices/{device-name}/command
  -> test publisher command subscriber
  -> device state update
  -> DeviceStatus snapshot / telemetry update
  -> dashboard 반영
```

## 데모 진행 순서

### 1단계: device 등록 상태 확인

확인할 것:

- KubeEdge `DeviceModel`이 존재한다.
- KubeEdge `Device`가 존재한다.
- 각 device가 의도한 node에 할당되어 있다.

대표 확인 관점:

```text
Device CR exists
Device.spec.nodeName is set
Device model is mapped
```

### 2단계: mapper 상태 확인

확인할 것:

- Jetson node의 `mqttvirtual` mapper가 Running이다.
- Raspberry Pi node의 `mqttvirtual` mapper가 Running이다.
- mapper가 edgecore/DMI socket과 연결 가능한 상태다.

### 3단계: publisher 실행

Jetson device는 Jetson node의 local mosquitto로 publish한다.

```bash
DEVICE_PLAN=jetson SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

Raspberry Pi device는 Raspberry Pi node의 local mosquitto로 publish한다.

```bash
DEVICE_PLAN=rpi SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

단일 device 확인이 필요하면 다음처럼 실행한다.

```bash
DEVICE_FILTER=vib-device-01 SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

### 4단계: telemetry freshness 확인

확인할 것:

- InfluxDB에 latest telemetry가 들어온다.
- `state-aggregator`의 `/state/devices`에서 `telemetry_fresh=true`로 표시된다.
- telemetry가 없으면 degraded reason에 원인이 표시된다.

### 5단계: DeviceStatus freshness 확인

확인할 것:

- DeviceStatus snapshot timestamp가 dashboard freshness 기준을 만족한다.
- raw telemetry 값이 DeviceStatus에 직접 올라가지 않는다.
- `health`, `severity`, `power`, `mode`, `sampling_interval`, `command_state` 같은 운영 상태 중심 값만 확인한다.

### 6단계: dashboard 확인

확인할 것:

- 전체 device 수
- live 또는 operational device 수
- degraded device 수
- telemetry freshness
- DeviceStatus freshness
- service-connected 또는 service-bound device 수
- node별 상태
- operator focus / issue list

### 7단계: 생산성 효과 설명

운영자가 dashboard를 통해 다음을 빠르게 판단할 수 있음을 설명한다.

- 어떤 device가 live인지
- 어떤 device가 service demo에 연결되어 있는지
- 어떤 node에서 문제가 발생했는지
- telemetry 문제인지 DeviceStatus 문제인지
- mapper 문제인지 publisher 실행 위치 문제인지
- 어떤 device를 먼저 점검해야 하는지

## 정상 동작 기준

정상 동작 상태는 다음 조건을 만족한다.

1. Device CR이 등록되어 있다.
2. Device가 의도한 node에 할당되어 있다.
3. 해당 node가 Ready 상태다.
4. mapper pod가 Running이다.
5. publisher가 해당 node의 local mosquitto로 telemetry를 publish한다.
6. InfluxDB latest telemetry가 dashboard freshness 기준을 만족한다.
7. DeviceStatus snapshot이 dashboard freshness 기준을 만족한다.
8. dashboard에서 device가 service demo group에 표시된다.
9. KPI가 현재 상태를 설명할 수 있다.

## 비정상/저하 상태 예시

| 상태 | dashboard 표시 | 해석 |
|---|---|---|
| publisher 미실행 | degraded | Device는 등록됐지만 telemetry가 들어오지 않음 |
| publisher 실행 node 불일치 | degraded | Device nodeName과 local broker publish 위치가 맞지 않음 |
| mapper 미동작 | unavailable | mqttvirtual device 처리 경로가 끊김 |
| DeviceStatus stale | degraded | telemetry는 있으나 운영 snapshot이 오래됨 |
| InfluxDB latest 없음 | degraded | mapper는 있으나 raw telemetry data-plane 확인이 안 됨 |
| node unavailable | unavailable | device가 할당된 node 상태가 불안정함 |

## KPI 후보

현재 서비스 데모에서 사용할 수 있는 KPI 후보는 다음이다.

| KPI | 의미 | 설명 방식 |
|---|---|---|
| registered_device_count | 등록 device 수 | PoC에 등록된 device 규모 |
| live_device_count | live 판단 device 수 | dashboard 기준 현재 살아 있는 device 수 |
| telemetry_device_count | fresh telemetry device 수 | raw telemetry data-plane 가시성 |
| service_bound_device_count | service demo에 연결된 device 수 | 디바이스-서비스 연결 구조 가시화 |
| degraded_device_count | degraded device 수 | 운영자가 확인해야 할 대상 |
| operator_focus_count | 우선 점검 대상 수 | 수동 점검 범위 감소 효과 |
| telemetry_freshness_ratio | fresh telemetry 비율 | data-plane 안정성 지표 |
| device_status_freshness_ratio | fresh DeviceStatus 비율 | status-plane 안정성 지표 |

현재 dashboard/API의 service binding KPI는 다음 이름을 사용한다.

```text
service_bound_device_count
device_service_binding_ratio
```

이 값은 workflow orchestration이 아니라 service binding 의미로 해석한다.

## 생산성 향상 효과 설명

현재 데모에서 생산성 향상 효과는 다음 언어로 설명한다.

1. 운영자가 여러 node와 device 로그를 따로 확인하지 않아도 된다.
2. dashboard에서 device, node, telemetry, status를 한 화면에서 확인한다.
3. degraded reason을 통해 원인 후보를 좁힐 수 있다.
4. service-bound device 수를 통해 서비스와 연결된 device 범위를 확인한다.
5. operator focus list를 통해 먼저 점검할 device 또는 node를 줄인다.
6. 현장 상태를 KPI로 설명할 수 있어 실공장 적용성을 보여준다.

## 현재 데모에서 제외하는 것

다음은 이번 서비스 데모 시나리오의 목표가 아니다.

- workflow stage 자동 분해/실행
- runtime replanning
- placement engine 기반 자동 재배치
- cost model 기반 runtime offloading 판단
- agent-assisted planning 기반 서비스 구성
- LLM 기반 전역 제어
- 전체 플랫폼을 자율 제어 대상으로 두는 orchestration 구조

위 항목은 현재 연구 방향에서 진행하는 다음 단계로 표현하지 않는다. 필요한 경우 과거 실험 또는 archive 자료로만 다룬다.

## 데모 성공 기준

서비스 데모는 다음을 만족하면 성공으로 본다.

1. Jetson 또는 Raspberry Pi 계열 device가 등록되어 있다.
2. publisher 실행 후 InfluxDB latest telemetry가 갱신된다.
3. DeviceStatus snapshot이 운영 상태 중심으로 갱신된다.
4. dashboard에서 healthy/degraded/unavailable이 정책 기준대로 표시된다.
5. service demo group에서 device-service 연결 관계를 확인할 수 있다.
6. KPI로 현재 상태와 운영 효과를 설명할 수 있다.
7. degraded 상태가 발생했을 때 원인 후보를 dashboard reason으로 좁힐 수 있다.

## 관련 문서

- `docs/current-demo-path.md`: 현재 device/MQTT/mapper/state-aggregator/dashboard 연결 경로
- `docs/device-service-binding.md`: 디바이스-서비스 연결 구조
- `docs/device-status-policy.md`: DeviceStatus와 raw telemetry 분리 정책
- `docs/dashboard-policy.md`: dashboard 상태 판단 기준
- `docs/scope.md`: 현재 범위와 제외 범위
