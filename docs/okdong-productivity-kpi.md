# 옥동 시나리오 생산성 KPI

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC를 옥동 시나리오와 같은 실공장 적용 관점에서 설명하기 위한 KPI를 정리한다.

목표는 복잡한 자동 제어를 주장하는 것이 아니라, 운영자가 dashboard를 통해 device, node, telemetry, DeviceStatus, service demo 연결 상태를 빠르게 이해하고 점검 대상을 줄일 수 있음을 설명하는 것이다.

## 한 줄 정의

```text
혼합 디바이스 상태를 한 화면에서 보고, 문제 위치를 빠르게 좁혀 현장 점검 시간을 줄이는 운영 가시화 PoC
```

## 현장 문제

옥동 시나리오에서 설명할 현장 문제는 다음이다.

1. Jetson, Raspberry Pi, x86 서버, 센서/가상 device가 섞여 있어 상태 확인 경로가 분산된다.
2. Device CR이 있어도 실제 telemetry가 들어오는지 바로 알기 어렵다.
3. raw telemetry와 DeviceStatus snapshot이 섞이면 정상/이상 판단 기준이 불명확해진다.
4. 장애가 발생했을 때 device 문제인지, node 문제인지, mapper 문제인지, publisher 실행 위치 문제인지 빠르게 구분하기 어렵다.
5. 운영자가 여러 명령과 로그를 직접 확인해야 하므로 점검 시간이 길어진다.

## 데모가 보여주는 개선점

현재 데모는 다음 개선점을 보여준다.

| 개선점 | dashboard에서 보는 항목 | 운영자 의미 |
|---|---|---|
| device 등록 가시화 | registered device count, device list | 어떤 device가 관리 대상인지 확인 |
| live 상태 가시화 | live device count, fresh_telemetry_device_count, telemetry_freshness_ratio | 실제 데이터가 들어오는 device 확인 |
| status-plane 분리 | device_status_freshness_ratio | 운영 snapshot 최신성 확인 |
| node/mapper 원인 분리 | Kubernetes Ready, dashboard node_ready, mapper_running | Kubernetes Ready(`kubectl get nodes`)와 dashboard `node_ready`(Prometheus/node-exporter 기반 node_health 판단)를 구분해 원인을 분리 |
| service 연결 가시화 | service_demo_group, service_bound_device_count | device가 어떤 서비스 데모에 쓰이는지 확인 |
| 우선 점검 대상 축소 | operator_focus_count, issue list | 운영자가 먼저 볼 device를 줄임 |

## KPI 목록

### 1. 등록 디바이스 수

| 항목 | 내용 |
|---|---|
| 이름 | registered_device_count |
| 의미 | KubeEdge에 등록된 device 수 |
| dashboard/API | `kpis.registered_device_count` |
| 운영자 해석 | 현재 관리 대상 device 규모 |

설명 문구:

```text
현재 dashboard는 등록된 device 전체를 기준으로 운영 상태를 보여준다. 운영자는 관리 대상 범위를 먼저 확인할 수 있다.
```

### 2. live device 수

| 항목 | 내용 |
|---|---|
| 이름 | live_device_count |
| 의미 | telemetry/status/node/mapper 기준으로 live로 볼 수 있는 device 수 |
| dashboard/API | `kpis.live_device_count` |
| 운영자 해석 | 지금 실제로 관측 가능한 device 규모 |

설명 문구:

```text
등록만 된 device와 실제 데이터가 들어오는 device를 구분해 현장 관측 가능 범위를 확인한다.
```

### 3. telemetry configured 비율

| 항목 | 내용 |
|---|---|
| 이름 | device_telemetry_ratio |
| 의미 | telemetry 수집이 설정된 device 비율(telemetry-enabled device / 전체 registered device) |
| dashboard/API | `kpis.telemetry_device_count`, `kpis.device_telemetry_ratio` |
| 운영자 해석 | telemetry를 받도록 설정된 관리 대상 범위 |

설명 문구:

```text
telemetry 설정 비율은 운영 대상 범위를 보여주고, 실제 최신 여부는 별도 freshness KPI로 분리한다.
```

### 4. telemetry freshness 비율

| 항목 | 내용 |
|---|---|
| 이름 | telemetry_freshness_ratio |
| 의미 | telemetry-enabled device 중 InfluxDB device-level latest sample이 fresh한 비율 |
| dashboard/API | `kpis.fresh_telemetry_device_count`, `kpis.telemetry_freshness_ratio`, `devices[].telemetry_fresh` |
| 운영자 해석 | 센서/publisher/MQTT/InfluxDB 경로가 살아 있는지 판단 |

InfluxDB timestamp 의미는 `docs/current-demo-path.md`의 data-plane 설명을 따른다. InfluxDB UI의 `_start`와 `_stop`은 Flux query 조회 window이며 device start/stop 이벤트가 아니다. 실제 telemetry sample timestamp는 `_time`이다. Dashboard의 `telemetry_fresh`는 device-level latest sample 기준이며, property별 latest freshness를 보장하지 않는다.

설명 문구:

```text
raw telemetry가 최근 들어오는지 따로 보이므로, DeviceStatus와 섞지 않고 data-plane 문제를 확인할 수 있다.
```

### 5. DeviceStatus freshness 비율

| 항목 | 내용 |
|---|---|
| 이름 | device_status_freshness_ratio |
| 의미 | DeviceStatus snapshot이 dashboard 기준 시간 안에 갱신된 device 비율 |
| dashboard/API | `kpis.fresh_device_status_count`, `kpis.device_status_freshness_ratio`, `devices[].device_status_fresh`, `devices[].device_status_last_reported_at` |
| 운영자 해석 | health, severity, power, mode, command_state 같은 운영 snapshot 최신성 확인. healthy 필수 조건은 아님 |

설명 문구:

```text
DeviceStatus는 raw telemetry 저장소가 아니라 운영 snapshot이다. dashboard는 data-plane과 status-plane을 분리해 보여준다.
```

### 6. 서비스 연결 device 수

| 항목 | 내용 |
|---|---|
| 이름 | service_bound_device_count |
| 의미 | 서비스 데모에 연결되어 dashboard에서 해석 가능한 device 수 |
| dashboard/API | `kpis.service_bound_device_count`, `devices[].service_connected` |
| 운영자 해석 | device가 단순 등록을 넘어 서비스 데모와 연결되어 있는지 확인 |

설명 문구:

```text
운영자는 device가 어떤 서비스 데모 그룹에 쓰이는지 확인하고, 서비스 영향 범위를 바로 볼 수 있다.
```

### 7. 디바이스-서비스 연결 비율

| 항목 | 내용 |
|---|---|
| 이름 | device_service_binding_ratio |
| 의미 | 등록 device 중 service demo group에 연결된 device 비율 |
| dashboard/API | `kpis.device_service_binding_ratio`, `devices[].service_demo_group` |
| 운영자 해석 | 서비스 관점으로 해석 가능한 device 범위 |

설명 문구:

```text
device 목록을 서비스 데모 그룹으로 묶어 보여주므로, 현장 운영자가 서비스별 상태를 이해하기 쉽다.
```

### 8. 운영자 우선 점검 대상 수

| 항목 | 내용 |
|---|---|
| 이름 | operator_focus_count |
| 의미 | degraded/unavailable device 수 + non-healthy node 수 |
| dashboard/API | `kpis.operator_focus_count`, issue/focus list |
| 운영자 해석 | 전체 device를 다 보지 않고 우선 점검 대상을 좁힘 |

설명 문구:

```text
운영자는 전체 device를 하나씩 확인하지 않고, degraded/unavailable device와 non-healthy node로 좁혀진 우선 점검 대상부터 확인할 수 있다. workflow risk는 현재 데모 범위의 operator_focus_count에 포함하지 않는다.
```

### 9. 문제 위치 분리 가능성

| 항목 | 내용 |
|---|---|
| 이름 | issue localization |
| 의미 | 문제 원인이 device, node, mapper, telemetry, DeviceStatus 중 어디에 가까운지 좁힐 수 있는지 |
| dashboard/API | `devices[].reason`, `devices[].mapper_running`, `devices[].node_ready`, `devices[].telemetry_fresh`, `devices[].device_status_fresh` |
| 운영자 해석 | 원인 후보를 빠르게 줄여 점검 시간을 줄임 |

설명 문구:

```text
dashboard reason을 통해 publisher 미실행, node 불일치, mapper 문제, telemetry 미수신, DeviceStatus stale 상태를 구분한다.
```

## 서비스 데모 그룹별 해석

| service_demo_group | 관련 device | 운영자 해석 |
|---|---|---|
| 설비 상태 모니터링 | `vib-device-*`, `rpi-vib-device-*` | 설비 진동/이상 징후 관측 경로 |
| 환경 상태 모니터링 | `env-device-*`, `temp-device-01`, `rpi-env-device-*` | 현장 온도/습도 등 환경 관측 경로 |
| command 상태 확인 | `act-device-*`, `rpi-act-device-*` | actuator command 적용 상태 확인 경로 |

## 데모 중 설명 순서

1. 등록 device 수를 보여준다.
2. Jetson/Raspberry Pi에 device가 나뉘어 할당되어 있음을 보여준다.
3. telemetry freshness와 DeviceStatus freshness가 분리되어 있음을 보여준다.
4. device가 service demo group으로 묶여 있음을 보여준다.
5. degraded 또는 unavailable device가 있으면 reason으로 원인을 좁히는 과정을 보여준다.
6. operator_focus_count를 통해 운영자가 우선 점검해야 할 대상이 줄어드는 것을 설명한다.
7. 이를 현장 점검 시간 단축, 원인 파악 경로 단순화, 서비스 영향 범위 확인으로 연결해 설명한다.

## 발표/보고서용 요약 문구

```text
본 PoC는 Jetson, Raspberry Pi, x86 서버가 혼재된 실공장형 edge 환경에서 device 등록 상태, telemetry freshness, DeviceStatus snapshot, mapper/node 상태, service demo 연결 구조를 통합 dashboard로 가시화한다. 운영자는 전체 device를 개별 명령으로 확인하지 않고 dashboard의 issue/focus list와 service binding 정보를 통해 우선 점검 대상을 좁힐 수 있으며, 이를 통해 현장 점검 시간 단축과 운영 가시성 향상 효과를 설명할 수 있다.
```

## 현재 범위에서 말하지 않는 것

다음은 현재 KPI 설명에 포함하지 않는다.

- 동적 workflow 실행 성능
- runtime offloading 판단 성능
- placement engine 기반 자동 재배치 효과
- agent-assisted planning에 의한 자동 작업 분해 효과
- LLM 기반 전역 제어 효과

위 항목은 현재 연구 방향의 KPI가 아니며, 필요한 경우 archive 자료의 과거 검토 내용으로만 다룬다.
