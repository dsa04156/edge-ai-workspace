# 현재 데모 흐름

## 한 줄 요약

현재 데모 흐름은 device 등록, MQTT telemetry/command topic, mapper 연동, telemetry/status 분리, 상태 통합, dashboard 가시화, read-only 운영 설명으로 이어진다.

## 현재 기준

운영 경로:

```text
Device registration
  -> edge node assignment
  -> MQTT telemetry / command topic
  -> mqttvirtual mapper / MapperFramework DMI adapter
  -> DeviceStatus status/control snapshot
  -> InfluxDB raw telemetry latest sample
  -> state-aggregator
  -> dashboard
  -> read-only operator assistant summary
```

향후 raw telemetry 경로는 별도 plane으로 분리한다.

```text
raw telemetry ingestion
  -> EdgeX Device Service / EdgeX MessageBus
  -> telemetry store / analytics consumers
```

## Device와 Node 규칙

KubeEdge `Device`는 현재 사전 등록 방식이다.
센서가 MQTT에 publish한다고 KubeEdge `Device`가 자동 생성되지는 않는다.

현재 할당 규칙:

| Device 계열 | 할당 node |
|---|---|
| Jetson 계열 | `etri-dev0001-jetorn` |
| Raspberry Pi 계열 | `etri-dev0002-raspi5` |

현재 dashboard는 `etri-dev0001-jetorn`에 할당된 Arduino 환경/진동 센서들을 중심으로 보여준다.

## MQTT Topic

topic 규칙:

```text
factory/devices/{device-name}/telemetry
factory/devices/{device-name}/command
factory/devices/{device-name}/heartbeat
```

| Topic | 의미 |
|---|---|
| `telemetry` | 센서 또는 테스트 publisher가 발행하는 raw sensor 입력 |
| `command` | mapper가 발행하고 테스트 publisher가 구독하는 command 경로 |
| `heartbeat` | 테스트 publisher 보조 heartbeat |

`heartbeat`는 현재 KubeEdge Device manifest에 직접 연결하지 않는다.
테스트 publisher는 실행한 서버의 로컬 mosquitto, 즉 `127.0.0.1:1883`로 publish한다.

## Service Binding 의미

device-service binding은 다음 관계를 뜻한다.

```text
Device -> node -> telemetry / status -> service demo -> dashboard / KPI
```

이는 runtime workflow scheduling, dynamic offloading, placement engine 자동화, agent-assisted planning, LLM 기반 제어를 뜻하지 않는다.

backend가 service binding 필드를 계산하고 dashboard는 그 결과를 표시한다.
API가 `service_demo_group`과 binding metadata를 내려주는 경우 frontend에서 device 이름 매핑을 다시 하드코딩하지 않는다.

## Workflow Designer 경계

`edge-orch/workflow-designer/`는 read-only와 dry-run planning 표면이다.
service stage, input device, target node를 보여줄 수 있지만, 실제 Kubernetes 배포, placement engine 실행, MQTT command publish, Device CR 수정으로 설명하지 않는다.

## 관련 Wiki

- [운영 모델](operating-model.md)
- [상태와 텔레메트리](status-and-telemetry.md)
- [대시보드와 KPI 모델](dashboard-and-kpi.md)

## 근거 문서

- [현재 데모 경로](../current-demo-path.md)
- [디바이스-서비스 바인딩](../device-service-binding.md)
- [프로젝트 배경](../project-context.md)
- [프로젝트 범위](../scope.md)
