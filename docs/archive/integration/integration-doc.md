# 통합문서

이 문서는 현재 작업 판단을 빠르게 맞추기 위한 정리본이다.
긴 실험 로그와 과거 상세 기록은 `docs/archive/integration/integration-detail-log.md`에 보존한다.

---

## 0. 지금 한 줄 정의

현재 단계는 **혼합 디바이스 엣지 AI 플랫폼의 전체 동적 오케스트레이션을 먼저 완성하는 단계가 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 가시화하며 현장 생산성 향상 효과를 설명 가능한 서비스 데모로 만드는 단계**다.

장기적으로는 이 기반 위에 동적 워크플로우, 가상화, 스케줄링, 오프로딩 고도화를 붙인다.

---

## 1. 현재 우선순위

1. 서비스 데모 1종을 먼저 완성한다.
2. 디바이스 등록/관리 체계를 정리한다.
3. 디바이스-서비스 바인딩 구조를 구현한다.
4. 통합 대시보드에서 디바이스, 노드, 서비스, 상태, KPI를 함께 보이게 한다.
5. 옥동 시나리오의 생산성 향상 효과를 설명 가능한 지표로 정리한다.
6. 이후 동적 워크플로우, 스케줄링, 가상화, 고도화 오프로딩으로 확장한다.

현재 과장하면 안 되는 것:
- 완전 자율형 오케스트레이션
- LLM이 전체 제어를 수행한다는 주장
- 동적 워크플로우 전체 구현 완료
- 고도화 기능이 이미 실증 완료된 것처럼 보이는 표현

---

## 2. 현재 구현 상태

완료 또는 상당 부분 구현된 축:
- `state_aggregator`: KubeEdge Device/DeviceStatus, InfluxDB telemetry, Prometheus metric을 통합해 대시보드 상태 API 제공
- KubeEdge `mqttvirtual` mapper 기반 가상 디바이스 PoC
- DeviceModel / Device / DeviceStatus 연동 검증
- GitOps: Argo CD 기반 `state-aggregator`, `mqttvirtual-mapper`, Redis, NVIDIA device plugin 관리

현재 실제 작업의 중심:
- raw telemetry와 대표 운영 상태 분리
- 다중 가상 디바이스에서 DeviceStatus 요청 부하 안정화
- 대시보드에서 DeviceStatus snapshot freshness와 InfluxDB history freshness를 구분 표시

현재 데모 운영 경로는 `state_aggregator` 중심으로 단순화한다.
과거 워크플로우 실행/배치 실험 컴포넌트는 현행 대시보드와 데모 운영 경로에서 제외한다.

---

## 3. 테스트베드와 노드

현재 전제로 두는 노드:

| 구분 | hostname | 역할 | 비고 |
|---|---|---|---|
| 서버 1 | `etri-ser0001-CG0MSB` | 제어/추론 서버 | RTX 5060 Ti, `nvidia.com/gpu=1` |
| 서버 2 | `etri-ser0002-CGNMSB` | 워커/추론 서버 | RTX 5080, `nvidia.com/gpu=1` |
| Jetson | `etri-dev0001-jetorn` | edge AI device | ARM64, Jetson Orin Nano |
| Raspberry Pi 5 | `etri-dev0002-raspi5` | edge light device | ARM64, sensor/light preprocess |

현재 가상 디바이스 PoC는 Jetson과 Raspberry Pi edge node를 대상으로 진행한다.

---

## 4. 가상 디바이스 PoC

목표:
- 물리/가상 혼합 디바이스 관리 구조 검증
- DeviceTwin 기반 상태 반영 검증
- MQTT telemetry / command 경로 검증
- 디바이스 상태를 대시보드와 서비스 데모로 연결할 기반 확보

현재 설계:
- `env-device-01` ~ `env-device-08`
- `vib-device-01` ~ `vib-device-06`
- `act-device-01` ~ `act-device-06`
- Jetson 대상 총 20개 Device manifest 생성
- Raspberry Pi 대상 `rpi-env-device-01` ~ `04`, `rpi-vib-device-01` ~ `03`, `rpi-act-device-01` ~ `03` 추가
- 단일 검증용 `temp-device-01` 포함
- 현재 운영 대시보드 기준 총 31개 Device 등록

주요 경로:
- Device manifest 생성: `edge-device/scripts/generate_devices.py`
- Device manifest: `edge-device/devices.yaml`
- DeviceModel: `edge-device/models/`
- 배포 스크립트: `edge-device/scripts/deploy.sh`
- mapper 소스: `mappers/mqttvirtual/`
- 테스트 publisher: `mappers/script/test_device.py`

테스트 publisher 실행 기준:
- 이 스크립트는 실행한 서버의 mosquitto로 테스트 telemetry를 publish하는 로컬 publisher다.
- 서버가 Jetson인지 Raspberry Pi인지, 또는 다른 서버인지는 판단하지 않는다.
- 기본 broker는 실행한 서버의 로컬 MQTT broker(`127.0.0.1:1883`)다.
- 해당 서버의 mapper가 `Device.spec.nodeName`에 따라 자신에게 할당된 topic만 소비한다.
- Jetson에서 실행하면 Jetson 로컬 mosquitto로만 publish되므로 Jetson에 할당된 디바이스만 live 처리된다.
- Raspberry Pi에 할당된 `rpi-*` 디바이스를 live로 만들려면 Raspberry Pi 서버에서 같은 스크립트를 실행해야 한다.
- 기본 모드는 `SIMULATION_MODE=stable`이다. 모든 act device는 `power=on`, `health=ok`를 유지하고, vib device도 정상 범위 진동값을 발행한다.
- 장애/랜덤 상태 전이를 보고 싶을 때만 `SIMULATION_MODE=random ACT_STATE_CHANGE_PROBABILITY=0.15`처럼 명시해서 실행한다.
- 기본 실행:
  - `python3 mappers/script/test_device.py`
- 특정 디바이스 topic만 발행:
  - `DEVICE_FILTER=act-device-06 python3 mappers/script/test_device.py`
  - `DEVICE_FILTER=rpi-env-device-01 python3 mappers/script/test_device.py`
- 원격 broker로 발행해야 하는 경우:
  - `MQTT_HOST=<broker-ip> MQTT_PORT=1883 python3 mappers/script/test_device.py`
- 브로커 없이 topic/payload schema만 검증:
  - `SELF_TEST=1 python3 mappers/script/test_device.py`
  - `SELF_TEST=1 DEVICE_FILTER=act-device-06,rpi-env-device-01 python3 mappers/script/test_device.py`

`test_device.py`의 payload는 `DeviceModel`/`Device` property와 맞춰야 한다.
`env`는 `temperature`, `humidity`, `health`, `sampling_interval`을 발행하고,
`vib`는 `vibration`, `severity`, `alarm_latched`, `health`, `sampling_interval`을 발행하며,
`act`는 `power`, `mode`, `health`, `sampling_interval`을 발행한다.

현재 확인된 것:
- 단일 `temp-device-01` 기준 `DeviceStatus.status.twins.reported` 반영을 확인했다.
- 가상 디바이스 MQTT publish 경로는 정상 동작한다.
- `DeviceStatus` CR 생성에 필요한 cloudcore RBAC 문제는 수정했다.
- 20~30개 병렬 구간에서는 mapper와 DeviceStatus 요청 부하를 줄이는 방향으로 구조를 정리 중이다.

---

## 5. 디바이스 등록 전략

현재 데모 단계의 기본 방식:
- 물리 센서를 연결하기 전에 `DeviceModel`과 `Device` CR을 사전 등록한다.
- 각 Device는 특정 edge node의 `spec.nodeName`에 바인딩한다.
- mapper는 edgecore/DMI를 통해 해당 Device를 전달받고 정해진 telemetry topic을 구독한다.
- 실제 센서 수집 프로그램은 Device 이름과 topic 규칙에 맞춰 MQTT payload를 발행한다.
- 이 경우 센서를 꽂는 것만으로 자동 등록되는 것은 아니며, 사전 등록된 Device와 publisher 규칙이 맞아야 수집된다.

현재 권장 운영 방식:
- 데모와 PoC는 사전 등록 방식으로 간다.
- Jetson/Raspberry Pi별로 필요한 센서 수만큼 Device manifest를 생성한다.
- 실제 센서가 붙으면 센서 publisher가 `factory/devices/{device-name}/telemetry` 규칙으로 값을 보낸다.
- raw telemetry는 InfluxDB 등 data plane으로 저장하고, `DeviceStatus`에는 요약 상태만 올린다.

후속 확장 방향:
- 자동 발견과 자동 등록은 `edge-device-agent` 또는 별도 discovery controller로 분리한다.
- agent는 각 edge node에서 USB/I2C/GPIO/Serial/MQTT 기반 센서 discovery를 수행한다.
- 발견 결과는 중앙 등록 API 또는 Kubernetes API를 통해 `Device` CR 생성 요청으로 올린다.
- 중앙에서는 승인, 중복 확인, 노드 매핑, `DeviceModel` 선택, naming 정책을 적용한다.
- 자동 등록은 운영 안정성과 승인 절차가 필요하므로 현재 데모 완료 이후 단계적 과제로 둔다.

정리:
- 현재: 사전 등록 Device + mapper 구독 + 센서 publisher 연동
- 후속: edge discovery agent + 승인 기반 Device CR 자동 생성

---

## 6. DeviceStatus 정책

핵심 판단:
- KubeEdge 원래 방식에 맞춰 `DeviceStatus`는 디바이스별 저빈도 control/status-plane snapshot으로만 사용한다.
- `DeviceStatus`는 고속 telemetry 저장소가 아니다. 온도, 습도, 진동 같은 raw telemetry stream은 MQTT data-plane으로 받고 InfluxDB에 저장한다.
- 대시보드는 `DeviceStatus` snapshot freshness와 InfluxDB telemetry freshness를 분리해서 판단한다.
- `status.state=online`은 참고값일 뿐이며 live/healthy 판단의 단독 근거로 쓰지 않는다.

배경 오류:

```text
fail to report device states because of too many request
```

이 오류는 `ReportDeviceStates`와 `ReportDeviceStatus`를 너무 자주 또는 여러 디바이스가 동시에 호출할 때 발생한다.
따라서 `DeviceStatus`는 “빠른 telemetry stream”이 아니라 “저주기 최신 snapshot”으로 다룬다.

현재 정책:
1. Device `status.reportToCloud`는 기본적으로 끈다. `ReportDeviceStates`는 telemetry 수신마다 호출하지 않는다.
2. DeviceStatus twin reported 대상은 allowlist로 제한한다.
3. raw telemetry property는 `reportToCloud: false`로 두고 InfluxDB `pushMethod.dbMethod.influxdb2`로 저장한다.
4. mapper는 changed-only 방식으로 pending status cache를 flush한다.
5. 기본 주기는 `DEVICE_STATUS_FLUSH_SECONDS=30`, `DEVICE_STATUS_JITTER_SECONDS=10`, `DEVICE_STATUS_HEARTBEAT_SECONDS=120`이다.
6. 동일 값 반복 보고는 하지 않고, heartbeat 목적의 동일 값 재보고도 120초 이상으로 제한한다.
7. 실제 센서가 고빈도 데이터를 발행해도 DeviceStatus 주기를 올리지 않는다. 고빈도 원천 데이터는 MQTT/InfluxDB data-plane에서 처리하고, 대시보드 freshness는 현재 InfluxDB 적재/집계 주기에 맞춘다.
8. 현재 mapper 기반 PoC는 raw telemetry를 60초 주기로 InfluxDB에 적재하므로 `TELEMETRY_FRESH_SECONDS=90`을 사용한다. 실제 고빈도 consumer를 붙이면 이 freshness 기준은 data-plane 적재 주기에 맞춰 다시 낮출 수 있다.

DeviceStatus CR 구조:

```yaml
apiVersion: devices.kubeedge.io/v1beta1
kind: DeviceStatus
metadata:
  name: <device-name>
  namespace: default
  ownerReferences:
    - kind: Device
      name: <device-name>
spec: {}
status:
  state: online
  lastOnlineTime: "2026-04-24T07:43:51Z"
  twins:
    - propertyName: health
      reported:
        value: ok
        metadata:
          timestamp: "1777508184621"
          type: string
      observedDesired:
        value: ""
        metadata:
          timestamp: "1777508184621"
          type: string
```

필드 의미:
- `metadata.name`: `Device.metadata.name`과 같은 디바이스 이름이다.
- `ownerReferences`: 어떤 `Device`에서 생성된 `DeviceStatus`인지 연결한다.
- `status.state`: KubeEdge device state 값이다. `online`이 남아 있어도 단독 live 근거로 쓰지 않는다.
- `status.lastOnlineTime`: KubeEdge가 기록한 마지막 online 시각이다. 현재 환경에서는 twin이 갱신돼도 이 값이 갱신되지 않을 수 있다.
- `status.twins[].propertyName`: reported 값이 어떤 Device property인지 나타낸다.
- `status.twins[].reported.value`: mapper가 cloud로 보고한 최신 property 값이다.
- `status.twins[].reported.metadata.timestamp`: 해당 reported 값의 갱신 시각이다. 현재 대시보드 freshness 판단의 주 기준이다.
- `status.twins[].observedDesired`: cloud desired 값을 mapper가 관측했는지 확인하는 필드다. 현재 live 판단의 주 기준은 아니다.

대시보드 해석 원칙:
- `state=online`만 보고 `healthy`로 판단하지 않는다.
- `lastOnlineTime`보다 `twins[].reported.metadata.timestamp`가 더 최신이면 reported timestamp를 우선한다.
- reported timestamp가 `DEVICE_STATUS_FRESH_SECONDS` 이내면 최신 DeviceStatus snapshot으로 본다.
- reported timestamp가 freshness 기준을 넘으면 값이 남아 있어도 stale snapshot으로 보고 `degraded` 처리한다.
- 실제 live 여부는 InfluxDB 최신 telemetry timestamp 또는 mapper/MQTT last_seen 기준을 별도로 본다.

DeviceStatus property 의미:
- `health`: `ok` / `degraded` / `offline` / `unknown`
- `severity`: `normal` / `warning` / `critical`
- `alarm_latched`: `true` / `false`
- `power`: `on` / `off`
- `mode`: `auto` / `manual` / `idle` / `maintenance`
- `sampling_interval`: command/desired 반영 여부 확인용 저빈도 상태
- `config_version` 또는 `reported_config_version`: 설정 반영 버전
- `command_state`: `idle` / `pending` / `applied` / `failed`
- `last_error_code`, `last_error_message`: 최근 장애 요약
- `temperature_status`, `humidity_status`, `vibration_status`: raw 값이 아닌 요약 상태

현재 manifest 정책:
- 대시보드에서 최신 운영 snapshot으로 볼 property만 `reportToCloud: true`
- `temperature`, `humidity`, `vibration`, `rms`, `peak`, `waveform`, `raw_samples` 같은 raw telemetry는 `reportToCloud: false`
- 이력/그래프가 필요한 raw telemetry는 InfluxDB `pushMethod.dbMethod.influxdb2` 사용
- Device `status.reportToCloud: false`
- Device `status.reportCycle: 120000`

주의:
- `act-device-06 power:on`처럼 `DeviceStatus`에 값이 있어도 reported timestamp가 오래됐으면 현재값이 아니라 마지막 reported snapshot이다.
- 대시보드는 stale snapshot을 healthy/live로 표시하면 안 된다.

---

## 7. 대시보드 device 상태 판단 정책

2026-04-29 기준으로 `state-aggregator`의 device 판단 기준을 재정리했다.

핵심 결론:
- KubeEdge `Device` CR은 등록, 노드 할당, 프로토콜, property 같은 최소 메타데이터 기준으로 사용한다.
- `DeviceStatus`는 운영 상태와 설정 반영 상태를 담는 control/status-plane snapshot으로 사용한다.
- 실제 raw telemetry live 여부는 InfluxDB 최신 수신 시각으로 판단한다.
- `DeviceStatus` snapshot freshness와 telemetry freshness는 서로 다른 boolean으로 계산한다.
- 운영 대시보드에서는 `available/operational`과 `healthy/live`를 분리해서 표시한다.

현재 데이터 경로:

```text
MQTT telemetry
  -> mqttvirtual mapper
  -> DeviceStatus low-rate status snapshot
  -> InfluxDB device_telemetry bucket for history
  -> state-aggregator KubeEdge DeviceStatus + InfluxDB query
  -> device_status_fresh / telemetry_fresh / mapper_running / node_ready 계산
  -> dashboard 표시
```

현재 `state-aggregator` 판단 기준:
- `healthy`: telemetry가 필요한 디바이스는 InfluxDB latest timestamp와 DeviceStatus reported timestamp가 모두 fresh하고, `severity=critical`이 아니다. telemetry가 없는 actuator류는 DeviceStatus snapshot이 fresh하면 healthy로 본다.
- `degraded`: telemetry 또는 DeviceStatus 중 하나가 stale이거나, `severity=critical`이거나, 노드와 mapper는 살아 있지만 최근 telemetry가 없음.
- `unavailable`: 노드 미할당, 할당 노드 unavailable, mapper 미실행, 명시적 offline 상태

현재 코드 기준 device status 판단 순서:
1. Kubernetes `Device` 목록과 `DeviceStatus` 목록을 각각 조회한다.
2. 같은 namespace/name의 `DeviceStatus.status`가 있으면 `Device.status` 대신 병합해서 판단한다.
3. 노드 미할당 또는 할당 노드 `unavailable`이면 `unavailable`이다.
4. `mqttvirtual` 디바이스인데 해당 노드에 mapper Pod가 Running이 아니면 `unavailable`이다.
5. `health=offline` 또는 명시 상태값 `offline/disconnected/failed/unavailable/false`면 `unavailable`이다.
6. `twins[].reported.metadata.timestamp`와 `lastOnlineTime` 중 최신 timestamp를 DeviceStatus snapshot 기준으로 사용한다.
7. DeviceStatus timestamp가 `DEVICE_STATUS_FRESH_SECONDS` 이내면 `device_status_fresh=true`다.
8. InfluxDB latest telemetry timestamp가 `TELEMETRY_FRESH_SECONDS` 이내면 `telemetry_fresh=true`다.
9. `telemetry_fresh=true`이고 `device_status_fresh=true`이면 `severity=critical`이 아닌 한 `healthy`다.
10. `telemetry_fresh=true`이고 `device_status_fresh=false`이면 live data-plane은 살아 있지만 status snapshot은 stale이므로 `degraded`다.
11. `telemetry_fresh=false`이고 `device_status_fresh=true`이면 status snapshot은 있으나 raw telemetry가 stale하므로 `degraded`다.
12. 둘 다 false이면 노드/mapper 상태에 따라 `degraded` 또는 `unavailable`로 표시하고 reason에 원인을 남긴다.

상태 판단에 쓰는 실제 필드:
- `Device.spec.nodeName`: 어느 노드에 할당됐는지 확인한다.
- `Device.spec.protocol.protocolName`: `mqttvirtual` mapper 확인 여부를 결정한다.
- `Device.spec.properties[].pushMethod`: data-plane telemetry 대상인지 판단한다.
- `DeviceStatus.status.lastOnlineTime`: fallback DeviceStatus snapshot timestamp로 사용한다.
- `DeviceStatus.status.twins[].reported.metadata.timestamp`: DeviceStatus snapshot freshness의 우선 기준이다.
- InfluxDB `device_telemetry`: raw telemetry live/freshness 기준이다.

`/state/devices` 주요 응답 필드:

```json
{
  "name": "env-device-01",
  "nodeName": "etri-dev0001-jetorn",
  "kubeedge_state": "online",
  "device_status_fresh": true,
  "device_status_last_reported_at": "2026-04-24T07:43:51Z",
  "telemetry_fresh": true,
  "telemetry_last_seen_at": "2026-04-24T07:43:55Z",
  "mapper_running": true,
  "node_ready": true,
  "health": "ok",
  "severity": "normal",
  "overall_status": "healthy",
  "reason": "fresh DeviceStatus reported timestamp and recent telemetry"
}
```

현재 설정:
- InfluxDB URL: `http://influxdb.telemetry.svc.cluster.local:8086`
- org: `edgeai`
- bucket: `device_telemetry`
- measurement: `virtual_device_telemetry`
- tag: `device_id`, `device_type`, `property`
- field: `value`
- DeviceStatus freshness 기준: `DEVICE_STATUS_FRESH_SECONDS=90`
- telemetry freshness 기준: `TELEMETRY_FRESH_SECONDS=90`
- mapper heartbeat freshness 기준: `MAPPER_HEARTBEAT_FRESH_SECONDS=60`
- query window: `TELEMETRY_QUERY_WINDOW=-30m`

현재 검증 결과:
- 등록 Device: 31개
- DeviceStatus snapshot 갱신과 InfluxDB history 적재를 함께 확인해야 한다.
- Jetson/Raspberry Pi별 publisher가 실제로 떠 있지 않으면 해당 device는 stale 또는 degraded로 표시되는 것이 맞다.

해석:
- `DeviceStatus`에 `power:on` 같은 값이 있어도 timestamp가 오래됐으면 live가 아니라 마지막 reported snapshot이다.
- InfluxDB에 값이 있어도 DeviceStatus가 stale이면 KubeEdge reported path 문제를 별도로 봐야 한다.
- 대시보드에서는 snapshot freshness와 telemetry history freshness를 구분해서 보여야 한다.

운영 주의:
- `argocd-image-updater`가 `state-aggregator:latest` digest를 잘못 덮어쓰는 상황이 있어, `edge-orch-state-aggregator` Application의 image-updater annotation을 제거하고 digest를 수동 고정했다.
- `state-aggregator` 이미지를 수동 빌드/푸시할 때는 Argo CD Application의 `spec.source.kustomize.images` digest도 함께 갱신해야 한다.
- Argo CD Image Updater는 Application annotation이 있는 앱만 감시한다. 현재 데모 안정화 단계에서는 `state-aggregator`와 `mqttvirtual-mapper` 모두 image-updater annotation을 두지 않는다.

---

## 8. Mapper 구성 방향

KubeEdge Mapper Framework 방향:
- `DeviceModel` / `Device` CRD로 모델과 인스턴스를 정의한다.
- DMI를 통해 edgecore가 mapper에 device/model 변경을 전달한다.
- `device/` 계층은 framework 공통 흐름에 가깝게 유지한다.
- 프로토콜 특화 구현은 `driver/`에 둔다.

현재 `mqttvirtual` 역할:
- MQTT broker 연결
- 디바이스별 telemetry topic subscribe
- command topic publish
- `visitor.configData.jsonKey` 기준 payload key와 Device property 매핑
- latest value cache 유지
- reported twin 생성에 필요한 이벤트 전달

남은 안정화 방향:
- 디바이스별 MQTT client 구조가 병렬 구간에서 불안정하면 broker 단위 shared client 또는 connection manager를 검토한다.
- `device/` 계층의 정책성 코드는 장기적으로 `driver/` 또는 명시 설정으로 밀어낸다.
- DeviceStatus 보고는 전체 manifest property 대상 최신 snapshot을 저빈도 flush로 유지한다.
- 빠른 telemetry history는 InfluxDB로 보내고, DeviceStatus는 최소 30초 수준으로 throttle한다.

---

## 9. 서비스 데모 방향

대표 데모는 다음 흐름을 반드시 보여야 한다.

```text
디바이스 입력
  -> MQTT telemetry
  -> AI/처리 서비스 실행
  -> 결과 전달
  -> 대시보드 표시
  -> 운영 상태/KPI 확인
```

대시보드에서 보여야 할 것:
- 어떤 센서/가상 디바이스가 연결되어 있는가
- 어떤 edge node가 활성 상태인가
- 어떤 서비스가 어느 노드에서 실행 중인가
- 어떤 디바이스가 어떤 서비스에 연결되어 있는가
- 장애, 미연결, 과부하, 성능저하가 있는가
- 시나리오별 처리 결과와 KPI가 무엇인가

권장 화면 구성:
1. 자산 현황
2. 디바이스-서비스 연결 관계
3. 운영 상태
4. 시나리오 KPI

---

## 10. 옥동 시나리오 KPI

옥동 시나리오는 단순 탐지 데모가 아니라 현장 생산성 향상 효과를 설명해야 한다.

정리해야 할 질문:
- 어떤 공정의 어떤 문제를 개선하는가
- 기존 수작업 또는 단순 룰 기반 방식 대비 무엇이 나아지는가
- 운영자 개입이 얼마나 줄어드는가
- 왜 AI 모델이 필요한가
- 어떤 지표로 생산성 향상을 설명할 것인가

사용 가능한 KPI:
- 응답 시간 단축
- 작업자 개입 횟수 감소
- 이상 대응 시간 감소
- 설비 가동 중단 감소
- 품질/안전 리스크 감소
- 현장 재설정 시간 감소

---

## 11. 런타임 오케스트레이션 장기 축

장기 연구 중심 문장:

**이기종 혼합 디바이스 엣지 AI 워크플로우를 위한 런타임 오케스트레이션**

장기 핵심 축:
1. workflow-stage decomposition
2. runtime state collection and normalization
3. stage-level placement / replanning / offloading
4. real mixed-device testbed validation

stage 예시:
- capture
- preprocess
- inference
- postprocess
- result delivery

초기 배치 원칙:
- heavy inference는 서버 우선
- 데이터 소스 인접 stage는 edge device 우선
- GPU-required stage는 서버 또는 Jetson만 허용
- unavailable node는 선택하지 않음
- overload 시 edge 재분산 또는 cloud offloading 검토

현재는 이 장기 축을 과장하지 않고, 데모와 연결 구조가 확보된 뒤 단계적으로 붙인다.
현재 운영 경로는 `state_aggregator` 중심으로 유지하고, 별도 워크플로우 실행/배치 컴포넌트는 포함하지 않는다.

---

## 12. 다음 실행 순서

1. `edge-device/scripts/deploy.sh`로 최신 DeviceModel/Device manifest를 적용한다.
2. 최신 `mqttvirtual` mapper 이미지를 빌드하고 edge node DaemonSet으로 재기동한다.
3. 각 서버에서 로컬 mosquitto로 필요한 MQTT payload를 발행한다.
4. `DeviceStatus.status.twins.reported`에 raw value가 아니라 요약 상태만 올라오는지 확인한다.
5. `ReportDeviceStates ... too many request` 오류가 사라졌는지 mapper 로그를 확인한다.
6. raw telemetry가 InfluxDB `device_telemetry` bucket에 저장되는지 확인한다.
7. `state-aggregator` `/state/devices`에서 `telemetry_last_seen`, `telemetry_age_seconds`, `status_reason`을 확인한다.
8. 디바이스-서비스 바인딩과 대시보드 표시 구조를 연결한다.
9. 자동 발견/자동 등록 controller는 데모 안정화 이후 후속 과제로 설계한다.

검증 기준:
- `temperature`, `humidity`, `vibration` 같은 raw telemetry는 DeviceStatus에 올라가지 않고 InfluxDB에 저장된다.
- `health`, `severity`, `alarm_latched`, `power`, `mode`, `sampling_interval`은 운영 상태 판단에 사용한다.
- Device `status.reportToCloud`는 false, `reportCycle`은 120000ms로 유지한다.
- mapper 로그에 DeviceStates rate limit 오류가 반복되지 않는다.
- 서비스 데모에서 raw telemetry는 별도 data plane으로 처리된다.
- dashboard의 `healthy`는 Device CR 존재 여부나 `state=online`이 아니라 DeviceStatus freshness와 InfluxDB `last_seen`을 분리해서 판단된다.

---

## 13. 산출물 우선순위

즉시 필요한 산출물:
1. 서비스 데모 시나리오 정의서
2. 디바이스 등록/관리 절차서
3. 디바이스-서비스 바인딩 명세
4. 통합 대시보드 정보 구조 정의서
5. 옥동 시나리오 생산성 KPI 정의서

그 다음:
6. 연차별 정량 목표 재정리표
7. 1000 디바이스 실증 단계 계획
8. 논문/특허/표준 실적 계획표

후속:
9. 동적 워크플로우 설계서
10. 오프로딩 및 재배치 정책 설계서
11. 가상화/스케줄링 고도화 설계서
12. agent-assisted planning 설계서

---

## 14. 참고 문서

상세 기록:
- `docs/archive/integration/integration-detail-log.md`

핵심 요약:
- `docs/archive/integration/integration-summary.md`

연구/논문 관련:
- `docs/research/paper-strategy.md`
- `docs/research/venue-strategy.md`
- `docs/research/evaluation-plan.md`
- `docs/research/writing-checklist.md`

시스템/운영 관련:
- `docs/archive/legacy-orchestration/system-overview.md`
- `docs/archive/legacy-orchestration/architecture.md`
- `docs/troubleshooting-network.md`
- `docs/archive/integration/handoff-legacy.md`
