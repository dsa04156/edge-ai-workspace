# Current Demo Runbook

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC의 서비스 데모 경로를 실행하고 점검하는 운영 절차를 정리한다.

범위는 device 등록 상태, mapper 상태, MQTT publisher, InfluxDB telemetry, DeviceStatus freshness, state-aggregator API, dashboard 확인까지다.

이 runbook은 workflow/offloading/agent-assisted planning 계열을 실행하기 위한 절차가 아니다.

## 전체 점검 흐름

```text
1. Kubernetes / KubeEdge node 확인
2. Device / DeviceStatus 확인
3. mapper pod 확인
4. edge node local mosquitto 확인
5. test publisher 실행
6. InfluxDB telemetry freshness 확인
7. state-aggregator API 확인
8. dashboard 확인
9. degraded reason 기반 troubleshooting
```

## 사전 조건

현재 데모 경로에서 필요한 구성 요소는 다음이다.

| 구성 요소 | 필요 상태 |
|---|---|
| Kubernetes control-plane | Ready |
| KubeEdge cloudcore / edgecore | 동작 중 |
| Jetson node | `etri-dev0001-jetorn` Ready |
| Raspberry Pi node | `etri-dev0002-raspi5` Ready |
| local mosquitto | 각 edge node의 `127.0.0.1:1883`에서 동작 |
| mqttvirtual mapper | edge node에서 Running |
| InfluxDB | telemetry namespace 또는 설정된 endpoint에서 동작 |
| state-aggregator | API 응답 가능 |
| dashboard | `/state/dashboard` 기반 화면 표시 가능 |

## 1. node 상태 확인

Kubernetes node 상태를 확인한다.

```bash
kubectl get nodes -o wide
```

확인할 것:

- `etri-ser0001-cg0msb`
- `etri-ser0002-cgnmsb`
- `etri-dev0001-jetorn`
- `etri-dev0002-raspi5`

각 node의 Ready 상태를 확인한다.

문제가 있으면 먼저 node join, edgecore, cloudcore 상태를 확인한다.

관련 문서:

- `docs/ops/node-join-check.md`
- `docs/ops/edge-node-join-check.md`
- `docs/ops/troubleshooting-network.md`

## 2. 주요 pod 상태 확인

전체 pod 상태를 확인한다.

```bash
kubectl get pods -A -o wide
```

특히 확인할 항목:

- `state-aggregator`
- `mqttvirtual` mapper pod
- InfluxDB pod
- Prometheus 관련 pod
- KubeEdge 관련 pod

mapper만 좁혀서 볼 때는 label 또는 이름 기준으로 확인한다.

```bash
kubectl get pods -A -o wide | grep -i mapper
```

주의:

- 이 문서는 조회 중심 runbook이다.
- 재시작, 삭제, 재배포 명령은 원인 확인 후 별도 절차로 수행한다.

## 3. Device 등록 상태 확인

KubeEdge Device CR을 확인한다.

```bash
kubectl get devices.devices.kubeedge.io -A
```

DeviceStatus CR을 확인한다.

```bash
kubectl get devicestatuses.devices.kubeedge.io -A
```

상세 확인이 필요하면 특정 device를 조회한다.

```bash
kubectl get devices.devices.kubeedge.io -A -o yaml
kubectl get devicestatuses.devices.kubeedge.io -A -o yaml
```

확인할 것:

- Device CR이 존재하는가?
- Device의 `spec.nodeName`이 의도한 node인가?
- `DeviceModel` 참조가 맞는가?
- DeviceStatus에 운영 snapshot이 있는가?
- DeviceStatus timestamp가 dashboard freshness 기준을 만족하는가?

## 4. nodeName 매핑 확인

현재 기준 device 배치는 다음을 따른다.

| device 계열 | nodeName |
|---|---|
| `env-device-*` | `etri-dev0001-jetorn` |
| `vib-device-*` | `etri-dev0001-jetorn` |
| `act-device-*` | `etri-dev0001-jetorn` |
| `temp-device-01` | `etri-dev0001-jetorn` |
| `rpi-env-device-*` | `etri-dev0002-raspi5` |
| `rpi-vib-device-*` | `etri-dev0002-raspi5` |
| `rpi-act-device-*` | `etri-dev0002-raspi5` |

publisher 실행 node와 `Device.spec.nodeName`이 맞지 않으면 dashboard에서 degraded로 보일 수 있다.

## 5. MQTT topic 규칙 확인

현재 topic 규칙은 다음이다.

```text
factory/devices/{device-name}/telemetry
factory/devices/{device-name}/command
factory/devices/{device-name}/heartbeat
```

각 topic의 역할:

| topic | 역할 |
|---|---|
| `telemetry` | raw telemetry 입력 |
| `command` | command 전달 |
| `heartbeat` | 테스트 publisher 보조 heartbeat |

`heartbeat`는 KubeEdge Device manifest에 직접 연결하지 않는다.

## 6. local mosquitto 확인

publisher는 실행한 서버의 local mosquitto로 publish한다.

```text
127.0.0.1:1883
```

Jetson device를 테스트할 때는 Jetson node에서 publisher를 실행한다.

Raspberry Pi device를 테스트할 때는 Raspberry Pi node에서 publisher를 실행한다.

local broker 상태 확인 예시는 다음이다.

```bash
systemctl status mosquitto
```

또는 port listen 상태를 확인한다.

```bash
ss -lntp | grep 1883
```

## 7. test publisher 실행

publisher 파일:

```text
mappers/script/test_device.py
```

기본 실행:

```bash
python3 mappers/script/test_device.py
```

Jetson device plan:

```bash
DEVICE_PLAN=jetson SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

Raspberry Pi device plan:

```bash
DEVICE_PLAN=rpi SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

전체 plan:

```bash
DEVICE_PLAN=all SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

단일 device:

```bash
DEVICE_FILTER=vib-device-01 SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

장애/변동 시나리오가 필요할 때만 random mode를 사용한다.

```bash
SIMULATION_MODE=random ACT_STATE_CHANGE_PROBABILITY=0.15 python3 mappers/script/test_device.py
```

주의:

- 안정적인 기본 데모는 `SIMULATION_MODE=stable`을 우선 사용한다.
- random mode는 dashboard의 degraded/alert 표시를 확인할 때만 사용한다.

## 8. state-aggregator API 확인

state-aggregator endpoint가 노출되어 있다면 다음 API를 확인한다.

```bash
curl -s http://localhost:8000/state/nodes
curl -s http://localhost:8000/state/devices
curl -s http://localhost:8000/state/dashboard
curl -s http://localhost:8000/state/summary
```

서비스가 cluster 내부에만 있으면 port-forward를 사용한다.

```bash
kubectl -n edge-orch port-forward svc/state-aggregator 8000:80
```

namespace나 service 이름이 다르면 현재 배포 상태에 맞춰 조정한다.

확인할 필드:

- `devices[].name`
- `devices[].node_name`
- `devices[].mapper_running`
- `devices[].node_ready`
- `devices[].telemetry_fresh`
- `devices[].device_status_fresh`
- `devices[].overall_status`
- `devices[].reason`
- `kpis.registered_device_count`
- `kpis.live_device_count`
- `kpis.device_telemetry_ratio`
- `kpis.operator_focus_count`

## 9. dashboard 확인

브라우저 또는 port-forward 경로로 dashboard를 확인한다.

확인할 영역:

1. active node count
2. registered device count
3. live device count
4. telemetry ratio
5. operator focus count
6. node list
7. device list
8. relation view
9. alert / issue list
10. scenario KPI

정상이라면 device, node, telemetry freshness, DeviceStatus freshness가 함께 표시된다.

## 10. 정상 상태 판단

정상 경로는 다음 조건을 만족한다.

1. node가 Ready다.
2. Device CR이 존재한다.
3. Device `nodeName`이 의도한 node다.
4. mapper pod가 Running이다.
5. publisher가 같은 node의 local mosquitto로 telemetry를 publish한다.
6. InfluxDB latest telemetry가 fresh하다.
7. DeviceStatus snapshot이 fresh하다.
8. dashboard에서 device가 healthy 또는 의도한 상태로 보인다.
9. service demo group 또는 relation view에서 device-service 연결을 해석할 수 있다.

## 11. degraded troubleshooting

### 증상 A: Device는 등록됐지만 degraded

가능한 원인:

- publisher가 실행되지 않았다.
- publisher가 잘못된 node에서 실행됐다.
- local mosquitto가 동작하지 않는다.
- mapper는 Running이지만 InfluxDB에 telemetry가 들어가지 않는다.
- DeviceStatus snapshot이 오래됐다.

확인 순서:

```bash
kubectl get devices.devices.kubeedge.io -A
kubectl get devicestatuses.devices.kubeedge.io -A
kubectl get pods -A -o wide | grep -i mapper
```

이후 publisher 실행 node와 `Device.spec.nodeName`을 비교한다.

### 증상 B: mapper is running but telemetry has not reached InfluxDB

의미:

- mapper pod는 Running으로 보인다.
- 그러나 InfluxDB latest telemetry가 dashboard freshness 기준을 만족하지 않는다.

확인할 것:

- publisher 실행 여부
- MQTT broker 주소
- `DEVICE_PLAN` / `DEVICE_FILTER`
- InfluxDB endpoint
- Device manifest의 `pushMethod.dbMethod.influxdb2`
- mapper log

### 증상 C: recent telemetry but DeviceStatus snapshot is stale

의미:

- raw telemetry data-plane은 살아 있다.
- DeviceStatus status-plane snapshot은 오래됐다.

확인할 것:

- DeviceStatus report 대상 property가 payload에 포함되어 있는가?
- mapper의 DeviceStatus allowlist 정책과 맞는가?
- `DEVICE_STATES_REPORT_ENABLED=false` 정책을 오해하고 있지 않은가?
- DeviceStatus는 raw telemetry 경로가 아니라 저빈도 운영 snapshot이라는 점을 확인한다.

### 증상 D: assigned mapper is not running

의미:

- `mqttvirtual` device인데 해당 node에서 mapper pod가 Running이 아니다.

확인:

```bash
kubectl get pods -A -o wide | grep -i mqttvirtual
kubectl get pods -A -o wide | grep etri-dev0001-jetorn
kubectl get pods -A -o wide | grep etri-dev0002-raspi5
```

### 증상 E: assigned node is unavailable

의미:

- Device가 할당된 node가 dashboard 기준 unavailable이다.

확인:

```bash
kubectl get nodes -o wide
kubectl describe node <node-name>
```

edge node라면 edgecore 상태와 cloudcore 연결 상태도 확인한다.

## 12. DeviceStatus 정책 확인

DeviceStatus에는 raw telemetry stream을 올리지 않는다.

허용되는 운영 snapshot 예시:

- `health`
- `severity`
- `alarm_latched`
- `power`
- `mode`
- `sampling_interval`
- `command_state`
- `temperature_status`
- `humidity_status`
- `vibration_status`

올리지 않는 raw stream 예시:

- `temperature`
- `humidity`
- `vibration`
- `rms`
- `peak`
- `raw_samples`
- `waveform`
- image / frame

자세한 기준은 `docs/device-status-policy.md`를 따른다.

## 13. 테스트 실행 기준

state-aggregator 코드 변경이 있을 때는 다음 명령으로 테스트한다.

```bash
cd /home/etri/jinuk/edge-orch/state-aggregator
PYTHONPATH=. .venv/bin/pytest -q tests
```

현재 문서 정리 단계에서는 코드 변경이 없으므로 테스트는 필수는 아니다.

## 14. 데모 전 체크리스트

데모 직전에는 다음을 확인한다.

- [ ] `kubectl get nodes -o wide`에서 주요 node가 Ready다.
- [ ] `kubectl get pods -A -o wide`에서 mapper와 state-aggregator가 Running이다.
- [ ] Device CR이 등록되어 있다.
- [ ] DeviceStatus CR을 조회할 수 있다.
- [ ] Jetson device publisher는 Jetson에서 실행했다.
- [ ] Raspberry Pi device publisher는 Raspberry Pi에서 실행했다.
- [ ] InfluxDB latest telemetry가 갱신된다.
- [ ] `/state/devices`에서 `telemetry_fresh`를 확인했다.
- [ ] `/state/devices`에서 `device_status_fresh`를 확인했다.
- [ ] dashboard에서 relation view와 KPI를 확인했다.
- [ ] degraded device의 reason을 설명할 수 있다.

## 현재 runbook 범위에서 제외하는 것

다음은 이 runbook의 실행 대상이 아니다.

- workflow stage 실행기 구동
- placement engine 구동
- runtime offloading 판단 실행
- agent-assisted planning 실행
- LLM 기반 전역 제어 실행
- 전체 플랫폼을 자율 제어 대상으로 두는 orchestration 실행

위 항목은 현재 연구 방향에서 진행하는 다음 단계로 표현하지 않는다. 필요한 경우 과거 검토/실험 또는 archive 자료로만 다룬다.

## 관련 문서

- `docs/current-demo-path.md`: 현재 device/MQTT/mapper/state-aggregator/dashboard 연결 경로
- `docs/device-service-binding.md`: 디바이스-서비스 연결 구조
- `docs/service-demo-scenario.md`: 서비스 데모 시나리오
- `docs/dashboard-information-structure.md`: dashboard 정보 구조
- `docs/device-status-policy.md`: DeviceStatus와 raw telemetry 분리 정책
- `docs/dashboard-policy.md`: dashboard 상태 판단 기준
