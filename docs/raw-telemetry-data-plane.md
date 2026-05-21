# Raw Telemetry Data Plane Architecture

## 목적

이 문서는 KubeEdge 기반 mixed-device PoC에서 raw sensor stream과 KubeEdge DeviceStatus를 분리하는 목표 구조를 정의한다.

핵심 방향은 다음이다.

- raw telemetry는 MQTT, Redis Streams, InfluxDB로 구성된 data-plane에서 처리한다.
- KubeEdge `DeviceStatus`와 `DeviceTwin reported`는 health, severity, alarm, status, command_state 같은 control/status-plane 상태만 담는다.
- `mqttvirtual` mapper는 raw telemetry 영구 저장 책임을 내려놓고 KubeEdge device runtime adapter 역할에 집중한다.
- dashboard는 live 값, history, health/freshness 판단을 서로 다른 저장소와 API에서 분리해서 읽는다.

## 전체 아키텍처 다이어그램

```text
Sensor / Arduino
  |
  |  MQTT publish: telemetry payload, 1s or faster
  v
MQTT Broker on edge node
  |
  +--------------------------------------------------------------+
  |                                                              |
  v                                                              v
raw-stream-bridge                                          mqttvirtual mapper
  |                                                        ------------------
  | MQTT subscribe                                        - MQTT subscribe
  | normalize envelope                                    - latest operational state cache
  | XADD telemetry:raw                                    - DeviceStatus/Twin reported
  | update telemetry:latest                               - desired/command handling
  | batch write to InfluxDB                               - KubeEdge DMI adapter
  | consumer group / replay                               - no raw telemetry persistence
  v
Redis Streams + Redis latest cache
  |
  | batch append / retry
  v
InfluxDB raw telemetry bucket
  |
  +----------------------+-------------------------------+
                         |
                         v
state-aggregator / dashboard
  ----------------------------
  - live sensor panel: Redis latest
  - historical graph: InfluxDB query
  - freshness/health: InfluxDB latest timestamp + KubeEdge/DeviceStatus
  - status/control display: DeviceStatus/Twin reported
```

## 컴포넌트 역할 정의

| 컴포넌트 | 책임 | 하지 않는 일 |
|---|---|---|
| Sensor/Arduino | 센서 샘플을 MQTT로 발행 | KubeEdge DeviceStatus 직접 수정 |
| MQTT Broker | edge node local telemetry/command broker | 장기 저장, 집계 |
| raw-stream-bridge | raw telemetry subscribe, Redis Streams append, latest cache, InfluxDB batch write | KubeEdge Device CR/DeviceStatus 수정, actuator command 실행 |
| Redis Streams | raw event buffer, replay, consumer group 기반 fan-out | 장기 history 저장의 최종 저장소 |
| Redis latest cache | dashboard live panel용 최신값 | freshness의 유일한 판단 근거 |
| InfluxDB | raw telemetry append 저장, history, graph, anomaly 분석, freshness latest timestamp | DeviceStatus/control-plane 저장소 |
| mqttvirtual mapper | KubeEdge DMI adapter, latest operational state, DeviceStatus/Twin reported, desired/command 처리 | raw telemetry 영구 저장, high-frequency sample history 보존 |
| state-aggregator | KubeEdge, mapper, InfluxDB, Redis latest를 조합해 dashboard API 생성 | raw telemetry를 DeviceStatus로 승격 |
| dashboard | live/history/status를 분리해 표시 | DeviceStatus를 raw telemetry 저장소처럼 사용 |

## Plane 분리 원칙

| 구분 | Data-plane | Control/status-plane |
|---|---|---|
| 대상 | raw/value/x/y/z/temperature/humidity/vibration 등 고빈도 값 | health/severity/alarm_latched/status/command_state 등 운영 상태 |
| 입력 | MQTT telemetry payload | mapper가 계산/반영한 operational state, desired/command 결과 |
| 최신값 | Redis `telemetry:latest:*` | mapper 내부 operational state, KubeEdge DeviceStatus |
| 이력 | InfluxDB raw append | KubeEdge DeviceStatus/Twin reported snapshot |
| dashboard 용도 | live sensor panel, graph, anomaly/history | health/status/control 상태 표시 |
| 저장 주기 | event-driven append 또는 짧은 batch | changed-only, throttled report |

## Redis Streams 설계

### Stream

기본 stream:

```text
telemetry:raw
```

권장 field:

| field | 설명 | 예시 |
|---|---|---|
| `device_id` | KubeEdge Device 이름 | `env-arduino-temperature-01` |
| `sensor` | 센서/property 이름 | `temperature`, `raw`, `x` |
| `value` | 샘플 값 | `28.1` |
| `edge_node` | edge node 이름 | `etri-dev0001-jetorn` |
| `topic` | 원본 MQTT topic | `etri/etri-dev0001-jetorn/arduino-001/temperature` |
| `timestamp` | source timestamp 또는 bridge receive timestamp, epoch ms 권장 | `1710000000000` |
| `received_at` | bridge 수신 epoch ms | `1710000000123` |
| `schema_version` | payload schema 버전 | `1` |

예시:

```json
{
  "device_id": "env-arduino-temperature-01",
  "sensor": "temperature",
  "value": 28.1,
  "edge_node": "etri-dev0001-jetorn",
  "topic": "etri/etri-dev0001-jetorn/arduino-001/temperature",
  "timestamp": 1710000000000,
  "received_at": 1710000000123,
  "schema_version": "1"
}
```

XADD 예시:

```bash
XADD telemetry:raw MAXLEN ~ 1000000 \
  device_id env-arduino-temperature-01 \
  sensor temperature \
  value 28.1 \
  edge_node etri-dev0001-jetorn \
  timestamp 1710000000000 \
  received_at 1710000000123
```

### Latest cache

권장 key:

```text
telemetry:latest:{device_id}
telemetry:latest:{device_id}:{sensor}
```

간단한 hash 방식:

```text
HSET telemetry:latest:env-arduino-temperature-01 \
  temperature.value 28.1 \
  temperature.timestamp 1710000000000 \
  temperature.received_at 1710000000123 \
  temperature.edge_node etri-dev0001-jetorn
```

property별 key 방식:

```text
HSET telemetry:latest:env-arduino-temperature-01:temperature \
  value 28.1 \
  timestamp 1710000000000 \
  received_at 1710000000123 \
  edge_node etri-dev0001-jetorn
```

권장 TTL:

```text
EXPIRE telemetry:latest:{device_id}:{sensor} 60
```

TTL은 dashboard live panel의 “방금 들어온 값” 표시용이다. 시스템 healthy 판단은 계속 InfluxDB latest timestamp를 우선한다.

### Consumer group

bridge 자체가 InfluxDB까지 쓰는 단일 프로세스로 시작할 수 있지만, 확장 시에는 consumer group을 분리한다.

```text
producer: raw-stream-bridge-ingest
stream:   telemetry:raw
consumer group:
  - influx-writer-group
  - anomaly-detector-group
  - dashboard-derived-metric-group
```

예시:

```bash
XGROUP CREATE telemetry:raw influx-writer-group $ MKSTREAM
XREADGROUP GROUP influx-writer-group writer-01 COUNT 500 BLOCK 1000 STREAMS telemetry:raw >
XACK telemetry:raw influx-writer-group <message-id>
```

## MQTT topic 구조

현재 PoC에는 두 계열 topic이 공존할 수 있다.

### 실제 Arduino/edge sensor topic

```text
etri/{edge_node}/{sensor_unit}/{sensor}
```

예시:

```text
etri/etri-dev0001-jetorn/arduino-001/temperature
etri/etri-dev0001-jetorn/arduino-001/light
etri/etri-dev0001-jetorn/arduino-001/magnetic
etri/etri-dev0001-jetorn/arduino-001/acceleration
```

### KubeEdge Device 단위 topic

```text
factory/devices/{device_id}/telemetry
factory/devices/{device_id}/command
```

권장 방향:

- raw-stream-bridge는 실제 sensor topic과 Device 단위 topic을 모두 subscribe 가능하게 둔다.
- topic-to-device mapping은 ConfigMap으로 관리한다.
- mapper는 command와 operational state에 필요한 topic만 유지한다.

예시 mapping:

```yaml
topic_mappings:
  - topic: etri/etri-dev0001-jetorn/arduino-001/temperature
    device_id: env-arduino-temperature-01
    sensor: temperature
    edge_node: etri-dev0001-jetorn
  - topic: etri/etri-dev0001-jetorn/arduino-001/acceleration
    device_id: vib-arduino-acceleration-01
    sensor_fields: [x, y, z]
    edge_node: etri-dev0001-jetorn
```

## raw-stream-bridge Python 예시 코드

아래 코드는 구조 예시다. 실제 배포 시에는 ConfigMap, Secret, graceful shutdown, retry/backoff, metrics를 추가한다.

```python
import json
import os
import signal
import time
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt
import redis
from influxdb_client import InfluxDBClient, Point, WriteOptions

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPICS = os.getenv("MQTT_TOPICS", "etri/+/+/+,factory/devices/+/telemetry").split(",")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis.telemetry.svc.cluster.local:6379/0")
STREAM_KEY = os.getenv("STREAM_KEY", "telemetry:raw")
LATEST_PREFIX = os.getenv("LATEST_PREFIX", "telemetry:latest")
MAXLEN = int(os.getenv("STREAM_MAXLEN", "1000000"))
LATEST_TTL_SECONDS = int(os.getenv("LATEST_TTL_SECONDS", "60"))

INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb.telemetry.svc.cluster.local:8086")
INFLUX_ORG = os.getenv("INFLUX_ORG", "edgeai")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "device_telemetry")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
MEASUREMENT = os.getenv("INFLUX_MEASUREMENT", "raw_sensor_telemetry")

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=WriteOptions(batch_size=500, flush_interval=1000))

@dataclass
class Sample:
    device_id: str
    sensor: str
    value: Any
    edge_node: str
    topic: str
    timestamp_ms: int
    received_at_ms: int

def now_ms() -> int:
    return int(time.time() * 1000)

def map_topic(topic: str, payload: dict[str, Any]) -> list[Sample]:
    received_at = now_ms()
    source_ts = int(payload.get("timestamp") or payload.get("source_ts") or received_at)

    # 실제 구현에서는 ConfigMap 기반 topic mapping을 사용한다.
    parts = topic.split("/")
    if topic.startswith("etri/") and len(parts) >= 4:
        edge_node = parts[1]
        sensor = parts[3]
        device_id = payload.get("device_id") or f"unknown-{sensor}"
    else:
        device_id = payload.get("device_id") or parts[2]
        sensor = payload.get("sensor") or "value"
        edge_node = payload.get("edge_node") or "unknown"

    samples: list[Sample] = []
    if sensor == "acceleration":
        for axis in ("x", "y", "z"):
            if axis in payload:
                samples.append(Sample(device_id, axis, payload[axis], edge_node, topic, source_ts, received_at))
    else:
        value = payload.get("value", payload.get(sensor, payload.get("raw")))
        if value is not None:
            samples.append(Sample(device_id, sensor, value, edge_node, topic, source_ts, received_at))
    return samples

def append_sample(sample: Sample) -> None:
    fields = {
        "device_id": sample.device_id,
        "sensor": sample.sensor,
        "value": str(sample.value),
        "edge_node": sample.edge_node,
        "topic": sample.topic,
        "timestamp": str(sample.timestamp_ms),
        "received_at": str(sample.received_at_ms),
        "schema_version": "1",
    }
    redis_client.xadd(STREAM_KEY, fields, maxlen=MAXLEN, approximate=True)

    latest_key = f"{LATEST_PREFIX}:{sample.device_id}:{sample.sensor}"
    redis_client.hset(latest_key, mapping=fields)
    redis_client.expire(latest_key, LATEST_TTL_SECONDS)

    point = (
        Point(MEASUREMENT)
        .tag("device_id", sample.device_id)
        .tag("sensor", sample.sensor)
        .tag("edge_node", sample.edge_node)
        .field("value", float(sample.value) if isinstance(sample.value, (int, float)) or str(sample.value).replace(".", "", 1).isdigit() else str(sample.value))
        .time(sample.timestamp_ms, write_precision="ms")
    )
    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)

def on_message(_client, _userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        for sample in map_topic(msg.topic, payload):
            append_sample(sample)
    except Exception as exc:
        print(f"bridge error topic={msg.topic} err={exc}", flush=True)

def main():
    client = mqtt.Client(client_id="raw-stream-bridge")
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    for topic in MQTT_TOPICS:
        client.subscribe(topic.strip(), qos=1)
    client.loop_start()

    stop = False
    def handle_stop(_sig, _frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    while not stop:
        time.sleep(1)

    client.loop_stop()
    write_api.flush()
    influx_client.close()

if __name__ == "__main__":
    main()
```

## InfluxDB write 구조

권장 measurement:

```text
raw_sensor_telemetry
```

권장 tags:

```text
device_id, sensor, edge_node, source, schema_version
```

권장 fields:

```text
value, raw_json(optional), quality(optional)
```

권장 timestamp:

- source timestamp가 있으면 source timestamp 사용
- 없으면 bridge receive timestamp 사용
- InfluxDB write 시각을 sample time으로 사용하지 않는다

예시 line protocol:

```text
raw_sensor_telemetry,device_id=env-arduino-temperature-01,sensor=temperature,edge_node=etri-dev0001-jetorn value=28.1 1710000000000000000
```

운영 정책:

- raw append는 batch write를 사용한다.
- batch size 예: 500~5000 points
- flush interval 예: 1~5초
- retry/backoff와 failed batch log를 둔다.
- retention policy를 분리한다.

권장 retention/downsampling:

| bucket | 용도 | 보존 |
|---|---|---|
| `device_telemetry_raw` | 1초 또는 고빈도 원본 | 7~30일 |
| `device_telemetry_1m` | 1분 downsample 평균/최대/최소 | 90~180일 |
| `device_telemetry` | 현재 dashboard 호환 latest/history | 전환기 호환용 |

PoC 최소 단계에서는 기존 `device_telemetry` bucket에 `raw_sensor_telemetry` measurement를 추가하고, 이후 bucket을 분리한다.

## Dashboard live/history/status 분리

| 화면 영역 | 데이터 소스 | 목적 |
|---|---|---|
| live sensor panel | Redis latest | 최근 1~2초 값 표시, 운영자가 센서 입력을 즉시 확인 |
| historical graph | InfluxDB | 시간대별 trend, anomaly, KPI 분석 |
| health/freshness | state-aggregator + InfluxDB latest timestamp | device healthy/degraded/unavailable 판단 |
| DeviceStatus panel | KubeEdge DeviceStatus/Twin reported | health, severity, alarm, command_state 같은 control/status-plane 표시 |
| service binding | state-aggregator backend fields | service demo group과 device 연결 표시 |

중요 정책:

- Redis latest는 live 표시용이다. Redis key TTL이 지났다고 바로 device healthy를 바꾸지 않는다.
- healthy 판단은 현재 방향대로 InfluxDB latest timestamp를 우선한다.
- DeviceStatus는 raw telemetry 저장소가 아니며, stale/fresh 여부를 별도 KPI로 표시한다.

## mapper에서 제거해야 하는 책임

`mqttvirtual` mapper에서 단계적으로 제거할 책임:

1. raw telemetry InfluxDB 영구 저장
2. raw/value/x/y/z/temperature/humidity/vibration 같은 high-frequency property의 DB pushMethod 처리
3. reportCycle 기반 latest snapshot을 raw history처럼 사용하는 구조
4. raw telemetry 값을 DeviceStatus/Twin reported에 올리는 경로
5. raw sample history 보존 책임
6. raw stream anomaly/history 분석을 위한 buffering 책임

mapper에 남길 책임:

1. KubeEdge DMI device runtime adapter
2. MQTT command publish
3. desired -> command 처리
4. latest operational state 유지
5. health/severity/alarm_latched/status/command_state 중심 DeviceStatus/Twin reported
6. mapper/node/device runtime 상태 관찰

## Device manifest 전환 방향

현재는 일부 raw property에 `pushMethod.dbMethod.influxdb2`가 있다. 목표 구조에서는 raw property의 DB pushMethod를 제거한다.

전환 전:

```yaml
properties:
  - name: raw
    reportToCloud: false
    pushMethod:
      dbMethod:
        influxdb2: ...
```

전환 후:

```yaml
properties:
  - name: health
    reportToCloud: true
  - name: severity
    reportToCloud: true
  - name: alarm_latched
    reportToCloud: true
  - name: command_state
    reportToCloud: true
```

raw sensor stream은 Device manifest의 DB pushMethod가 아니라 raw-stream-bridge mapping에서 처리한다.

## Migration 단계별 계획

### 0단계: 현 상태 고정

- 현재 mapper가 InfluxDB에 주기 snapshot을 쓰는 구조를 문서화한다.
- dashboard freshness가 InfluxDB latest timestamp 기준임을 유지한다.
- DeviceStatus allowlist를 유지한다.

### 1단계: raw-stream-bridge MVP 추가

- Redis 배포 또는 기존 Redis 연결을 준비한다.
- raw-stream-bridge를 추가한다.
- MQTT topic mapping ConfigMap을 작성한다.
- Redis `telemetry:raw` XADD와 `telemetry:latest:*` update를 먼저 검증한다.
- InfluxDB batch write를 추가한다.

### 2단계: dual-write 검증

- 짧은 기간 동안 mapper DB write와 bridge DB write를 동시에 유지한다.
- InfluxDB measurement를 분리한다.
  - mapper 기존: `virtual_device_telemetry`
  - bridge 신규: `raw_sensor_telemetry`
- 같은 device의 latest timestamp와 sample count를 비교한다.
- 1초 입력이면 bridge 측 sample count가 입력률과 맞는지 확인한다.

### 3단계: dashboard live/history 분리

- state-aggregator에 Redis latest client를 추가한다.
- dashboard live sensor panel은 Redis latest를 사용한다.
- historical graph는 InfluxDB `raw_sensor_telemetry`를 사용한다.
- health/freshness는 기존 정책대로 InfluxDB latest timestamp를 사용한다.

### 4단계: mapper raw DB write 제거

- Device manifest generator에서 raw property `pushMethod.dbMethod`를 제거한다.
- mapper의 InfluxDB DBMethod handler는 운영 상태/liveness 전용 또는 legacy optional로 축소한다.
- raw property는 `reportToCloud: false`를 유지하고 DeviceStatus allowlist 밖에 둔다.

### 5단계: 운영 정책 정리

- retention/downsampling bucket을 분리한다.
- raw-stream-bridge metrics와 alert를 추가한다.
- Redis stream pending/lag, Influx write failure, MQTT disconnect 상태를 dashboard issue로 노출한다.

## PoC 최소 구현 순서

1. `raw-stream-bridge` 단일 Python Deployment 작성
2. Redis Deployment/Service 추가
3. MQTT wildcard subscribe + topic mapping ConfigMap 작성
4. Redis Streams XADD 검증
5. Redis latest cache 검증
6. InfluxDB batch write 검증
7. state-aggregator에 Redis latest read API 추가
8. dashboard live sensor panel을 Redis latest 기반으로 추가
9. InfluxDB history query를 `raw_sensor_telemetry` 기준으로 추가
10. Device manifest에서 raw DB pushMethod 제거
11. mapper가 control/status-plane만 담당하도록 코드와 docs 정리

## 성공 기준

- 센서가 1초마다 publish하면 Redis Streams에는 1초 샘플이 append된다.
- InfluxDB raw measurement에도 1초 샘플이 batch write로 보존된다.
- mapper는 raw telemetry를 DB에 쓰지 않는다.
- DeviceStatus에는 raw/value/x/y/z/temperature 같은 값이 올라오지 않는다.
- dashboard live panel은 Redis latest 값을 보여준다.
- dashboard history graph는 InfluxDB raw history를 보여준다.
- dashboard healthy 판단은 InfluxDB latest timestamp와 KubeEdge/node/mapper 상태를 조합해 기존 정책대로 유지한다.
