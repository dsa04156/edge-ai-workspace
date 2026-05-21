# Raw Telemetry Data Plane Architecture

## 목적

이 문서는 현재 KubeEdge 기반 mixed-device PoC의 공식 raw telemetry 저장 경로를 정의한다.
현재 목표는 고도화된 raw stream architecture가 아니라, KubeEdge Device CR과 mapper-framework가 제공하는 표준 흐름을 우선 복구하는 것이다.

## 공식 구조

```text
Sensor / Arduino
  -> MQTT Broker
  -> mqttvirtual mapper
  -> LatestValues cache
  -> Device CR pushMethod.dbMethod.influxdb2
  -> InfluxDB
  -> state-aggregator / dashboard
```

## 현재 원칙

- raw sensor property는 Device manifest의 `pushMethod.dbMethod.influxdb2`를 사용한다.
- `mqttvirtual` mapper는 MQTT telemetry를 수신해 LatestValues cache에 보관하고, 각 property의 `reportCycle`/`collectCycle` 기준으로 InfluxDB에 저장한다.
- `DeviceStatus`는 raw telemetry 저장소가 아니다.
- `DeviceStatus`/Twin reported는 `health`, `severity`, `alarm_latched`, `command_state` 같은 control/status 보조 신호로 제한한다.
- `state-aggregator`의 telemetry freshness는 InfluxDB latest timestamp 기준으로 판단한다.
- dashboard는 InfluxDB latest sample과 DeviceStatus snapshot freshness를 분리해서 표시한다.

## 컴포넌트 역할

| 컴포넌트 | 책임 | 하지 않는 일 |
|---|---|---|
| Sensor/Arduino | 센서 값을 MQTT telemetry topic으로 발행 | KubeEdge DeviceStatus 직접 수정 |
| MQTT Broker | edge node local telemetry/command broker | 장기 저장, 대시보드 API 생성 |
| mqttvirtual mapper | MQTT subscribe, LatestValues cache, DMI adapter, `pushMethod.dbMethod.influxdb2` 기반 InfluxDB 저장, command publish | raw telemetry를 DeviceStatus에 올리기 |
| Device CR | property별 `collectCycle`, `reportCycle`, `pushMethod.dbMethod.influxdb2` 저장 정책 선언 | runtime sample 자체 저장 |
| InfluxDB | raw telemetry latest/history 저장과 freshness 판단 기준 제공 | control-plane 상태 저장소 역할 |
| state-aggregator | KubeEdge Device/DeviceStatus와 InfluxDB latest timestamp를 조합해 dashboard payload 생성 | Redis latest 조회, raw telemetry 별도 bridge 운영 |
| dashboard | 디바이스-서비스 연결 구조, 센서 데이터 freshness, status snapshot, KPI 가시화 | `status.state=online`만으로 healthy 판단 |

## Device CR property 정책

raw sensor property 예시는 다음과 같다.

```yaml
- name: temperature
  collectCycle: 60000
  reportCycle: 60000
  reportToCloud: false
  visitors:
    protocolName: mqttvirtual
    configData:
      dataType: string
      jsonKey: temperature
  pushMethod:
    dbMethod:
      influxdb2:
        influxdb2ClientConfig:
          url: http://influxdb.telemetry.svc.cluster.local:8086
          org: edgeai
          bucket: device_telemetry
        influxdb2DataConfig:
          measurement: virtual_device_telemetry
          tag:
            device_id: env-device-01
            device_type: env
            property: temperature
          fieldKey: value
```

정책:

- `env`/`rpi-env`: `temperature`, `humidity`는 InfluxDB 저장 대상이다.
- `vib`/`rpi-vib`: `vibration`은 InfluxDB 저장 대상이다.
- `act`/`rpi-act`: actuator liveness 확인용 `health` 저장 정책은 유지한다.
- raw sensor property는 `reportToCloud: false`로 두어 DeviceStatus에 고빈도 값을 올리지 않는다.
- actuator/status property의 `reportToCloud` allowlist는 기존 DeviceStatus 정책을 따른다.

## Mapper 저장 경로

`mqttvirtual` mapper는 Device CR의 `pushMethod.dbMethod`를 기준으로 DB handler를 실행한다.
`raw`, `value`, `x`, `y`, `z`, `temperature`, `humidity`, `vibration` 같은 raw property를 mapper DB 저장에서 제외하는 denylist는 공식 경로와 맞지 않으므로 사용하지 않는다.

InfluxDB method 이름은 mapper-framework 변환 결과와 legacy 호환을 위해 `influx`와 `influxdb2`를 모두 허용한다.

## state-aggregator / dashboard 정책

- Redis 없이 InfluxDB만 조회한다.
- `/state/dashboard` payload에는 `raw_telemetry_latest`를 포함하지 않는다.
- KPI에는 `raw_live_stream_count`를 포함하지 않는다.
- telemetry freshness는 기존처럼 InfluxDB latest timestamp 기준이다.
- DeviceStatus는 `health`, `severity`, `alarm_latched`, `command_state` 등 운영 snapshot 해석의 보조 신호로만 사용한다.

## Redis/raw-stream-bridge 위치

Redis Streams와 raw-stream-bridge 기반 구조는 현재 PoC 기본 경로가 아니다.
향후 고빈도 fan-out, replay, multi-consumer streaming이 필요할 때 실험적 대안으로 다시 검토할 수 있으나, 현재 공식 구현/문서/CI/CD 대상에서는 제외한다.
