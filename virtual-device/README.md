# Virtual Device Runtime

이 디렉터리는 2차년도 프로토타입용 Virtual Device Runtime이다. 기존
`sensor-collector/serial_mqtt_collector.py`와 분리된 독립 실행 단위이며 해당 파일을
대체하거나 수정하지 않는다.

## Virtual Device 정의

여기서 Virtual Device는 AI 서비스가 아니다. 물리 디바이스의 연결 프로토콜과 원본
필드 형식을 감추고, profile에 선언된 데이터만 표준 형태로 바꿔 로컬 MQTT Broker에
제공하는 컨테이너 기반 소프트웨어 서비스다.

```text
Serial JSON 진동센서
  -> SerialJsonAdapter
  -> profile 기반 mapping / duplicate·stale 검사
  -> 표준 Virtual Device telemetry
  -> 로컬 MQTT Broker
  -> 별도 AI 이상감지 서비스(이번 구현 범위 밖)
```

Virtual Device는 추론 모델을 실행하거나 결과를 분석하지 않는다. 물리 입력과 AI
서비스 사이에서 수집·표준화·상태 보고 경계를 제공한다.

## 디렉터리 구조

```text
virtual-device/
├── Dockerfile
├── pyproject.toml
├── profiles/
│   └── serial-vibration-example.yaml
├── virtual_device/
│   ├── main.py              # CLI, signal 처리, 객체 조립
│   ├── config.py            # YAML 검증과 설정 override
│   ├── models.py            # 표준 telemetry wire model
│   ├── normalizer.py        # mapping, 형 변환, duplicate/stale 판정
│   ├── publisher.py         # MQTT 및 테스트용 in-memory publisher
│   ├── runtime.py           # lifecycle, heartbeat, reconnect
│   ├── status.py            # runtime 상태 snapshot
│   └── adapters/
│       ├── base.py          # 최소 Adapter 인터페이스
│       ├── serial_json.py   # Serial line-delimited JSON
│       └── fake.py          # 장비 없는 테스트용 adapter
└── tests/
```

## Device Profile

예제는 `profiles/serial-vibration-example.yaml`에 있다. 요청된 profile 구조에
`capability` 필드를 하나 추가했다. capability는 출력 envelope에 반드시 필요하며
`virtualDeviceId` 문자열에서 암묵적으로 추론하면 이름 변경 시 의미가 달라질 수 있기
때문에 profile에서 명시한다.

핵심 영역은 다음과 같다.

- `virtualDeviceId`, `physicalDeviceId`, `nodeId`, `capability`: 표준 출력 identity
- `adapter`: `serial-json`과 Serial 연결 정보
- `mapping.timestampFields`: 첫 번째로 발견된 원본 timestamp를 `sourceTimestamp`로 보존
- `mapping.properties`: 출력이 허용된 원본 필드와 표준 필드명·형·단위
- `output.mqtt`: 로컬 Broker와 telemetry/status topic
- `runtime`: heartbeat, offline 판정, reconnect backoff

property의 기본 `required` 값은 `true`다. 선택 필드는 다음처럼 지정할 수 있다.

```yaml
mapping:
  properties:
    temperature:
      target: temperature
      type: float
      unit: celsius
      required: false
```

지원 형은 `float`, `int`, `string`, `bool`이다. 필수 property 누락이나 형 변환 실패는
Runtime을 종료하지 않는다. 존재하는 mapping 필드만 telemetry에 넣고
`quality.valid=false`, `quality.errors=[...]`로 명확히 표시한다. 원본 JSON 전체와
mapping에 없는 필드는 출력하지 않는다.

## 설정 우선순위

설정 우선순위는 다음과 같다.

```text
CLI > VD_* 환경변수 > 기존 collector 호환 환경변수 > YAML
```

| 설정 | CLI | 환경변수 | 기존 alias |
|---|---|---|---|
| MQTT host | `--mqtt-host` | `VD_MQTT_HOST` | `MQTT_HOST` |
| MQTT port | `--mqtt-port` | `VD_MQTT_PORT` | `MQTT_PORT` |
| Serial port | `--serial-port` | `VD_SERIAL_PORT` | `SERIAL_PORT` |
| baud rate | `--serial-baud-rate` | `VD_SERIAL_BAUD_RATE` | `BAUDRATE` |
| timeout | `--serial-timeout-seconds` | `VD_SERIAL_TIMEOUT_SECONDS` | `SERIAL_TIMEOUT_SECONDS` |

동일 설정에 `VD_*`와 기존 alias가 모두 있으면 `VD_*`를 사용한다.

## 로컬 실행

`virtual-device/` 디렉터리에서 실행한다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m virtual_device.main \
  --profile profiles/serial-vibration-example.yaml
```

실제 port를 CLI로 덮어쓰는 예시:

```bash
.venv/bin/python -m virtual_device.main \
  --profile profiles/serial-vibration-example.yaml \
  --serial-port /dev/ttyACM0 \
  --mqtt-host 127.0.0.1
```

Runtime은 publisher를 실행한 노드의 로컬 MQTT Broker를 대상으로 한다. 기본 profile은
`127.0.0.1:1883`을 사용한다.

## Docker 실행

Linux host의 Serial 장치와 로컬 Broker를 사용하는 예시다.

```bash
docker build -t edge-ai-virtual-device:0.1.0 .
docker run --rm \
  --network host \
  --device /dev/ttyACM0:/dev/ttyACM0 \
  edge-ai-virtual-device:0.1.0 \
  --profile profiles/serial-vibration-example.yaml
```

다른 profile을 mount할 때는 다음처럼 실행한다.

```bash
docker run --rm \
  --network host \
  --device /dev/ttyUSB0:/dev/ttyUSB0 \
  -v "$PWD/profiles:/profiles:ro" \
  edge-ai-virtual-device:0.1.0 \
  --profile /profiles/serial-vibration-example.yaml \
  --serial-port /dev/ttyUSB0
```

## 입력과 MQTT 출력

한 Serial line은 하나의 JSON object여야 한다.

```json
{"sensor":"vibration","device_id":"etri-pd0001-arduino","source_ts":1710000000,"x":0.12,"y":0.08,"z":0.91}
```

기본 topic:

```text
edge/virtual-devices/etri-vd0001-vibration/telemetry
edge/virtual-devices/etri-vd0001-vibration/status
```

표준 telemetry 예시:

```json
{
  "schemaVersion": "v1alpha1",
  "virtualDeviceId": "etri-vd0001-vibration",
  "physicalDeviceId": "etri-pd0001-arduino",
  "nodeId": "etri-dev0001-jetorn",
  "capability": "vibration",
  "sourceTimestamp": 1710000000,
  "collectedAt": 1710000001,
  "sequence": 1,
  "data": {
    "acceleration_x": {"value": 0.12, "unit": "g"},
    "acceleration_y": {"value": 0.08, "unit": "g"},
    "acceleration_z": {"value": 0.91, "unit": "g"}
  },
  "quality": {"valid": true}
}
```

`sourceTimestamp`는 물리 sample이 가진 원본 시각이고 `collectedAt`은 Runtime이 그
sample을 받은 시각이다. 두 값을 서로 덮어쓰지 않는다. 동일 source timestamp와 동일
표준 payload는 중복으로 억제한다. 비교 가능한 timestamp가 마지막 발행값보다 과거면
stale sample로 억제한다. 값이 같아도 source timestamp가 새로우면 새 sequence로
발행한다.

status/heartbeat 예시:

```json
{
  "virtualDeviceId": "etri-vd0001-vibration",
  "physicalDeviceId": "etri-pd0001-arduino",
  "phase": "running",
  "connection": "connected",
  "dataStatus": "fresh",
  "lastSeenAt": 1710000001,
  "lastError": null
}
```

phase는 `starting`, `running`, `degraded`, `stopped`, `failed`를 사용하고 connection은
`connected`, `disconnected`, `unknown`을 사용한다. 연결/품질 전이 시 즉시 status를
발행하고, 상태가 바뀌지 않아도 `heartbeatSeconds` 주기로 snapshot을 발행한다. Serial
연결 실패 시 `degraded`를 발행하고 `reconnectBackoffSeconds`부터 지수 backoff를
적용하며 `reconnectBackoffMaxSeconds`에서 상한을 둔다. SIGINT/SIGTERM을 받으면
adapter와 MQTT 연결을 닫고 마지막 `stopped` 상태를 발행한다.

## 테스트

대부분의 검증은 Serial 장비와 MQTT Broker 없이 실행된다.

```bash
.venv/bin/python -m pytest -q
```

`FakeAdapter`는 dict, JSON 문자열, 연결 예외를 순서대로 공급할 수 있다.
`InMemoryPublisher`는 발행 record를 메모리에 보관하므로 Runtime 전체 흐름을 실제
Broker 없이 검증한다.

## 현재 지원 범위

- line-delimited Serial JSON 입력
- YAML Device Profile 검증과 설정 override
- 선언된 mapping 필드만 표준 telemetry로 변환
- 로컬 MQTT telemetry/status 발행
- 상태 전이와 heartbeat
- duplicate/stale 억제
- 재연결 backoff와 정상 종료
- 테스트용 `FakeAdapter`, `InMemoryPublisher`

## 이번 버전에서 지원하지 않는 기능

- KubeEdge Device, DeviceModel, DeviceStatus CRD
- MapperFramework 수정
- EdgeX 또는 중앙 telemetry 전송
- Virtual Device Registry와 자동 탐색
- 웹 대시보드
- AI 서비스 실행과 분석
- 자원 증강, offloading, runtime migration
- 실제 Modbus, RTSP, OPC-UA adapter
- 복잡한 분산 오케스트레이션

## Adapter 확장 지점

새 adapter는 `virtual_device.adapters.base.Adapter`의 네 메서드만 구현한다.

```text
start()   물리 연결 열기
read()    원본 sample dict 하나 또는 timeout 시 None 반환
health()  connected/disconnected/unknown snapshot 반환
stop()    연결 닫기
```

그다음 `config.py`의 허용 `adapter.type`과 `main.py:create_adapter()`에 명시적으로 한
분기만 추가한다. 현재는 `SerialJsonAdapter`와 테스트용 `FakeAdapter`만 구현되어 있다.
MQTT 입력, Modbus, RTSP는 이 확장 지점을 설명하기 위한 후속 후보일 뿐 빈 구현이나
지원 기능으로 표시하지 않는다.
