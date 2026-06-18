# E2E 데모 검증

## 목적

이 문서는 KubeEdge 혼합 디바이스 PoC의 실제 실행 경로가 끝까지 동작하는지 read-only로 확인한다.

검증 경로:

```text
test_device.py
  -> edge node local MQTT broker(127.0.0.1:1883)
  -> mqttvirtual mapper
  -> KubeEdge Device / DeviceStatus
  -> InfluxDB
  -> state-aggregator
  -> dashboard
```

검증 대상은 서비스 데모와 통합 운영 가시화다. workflow/offloading/placement/autonomous agent 제어, MQTT command 실행, actuator command 실행은 이 문서의 대상이 아니다.

## 금지 명령

이 검증에서는 다음 명령을 실행하지 않는다.

```text
kubectl delete
kubectl apply
kubectl rollout restart
MQTT command publish
actuator command 실행
```

## 0. 빠른 보조 스크립트

repository root에서 실행한다.

```bash
bash tools/verify_e2e.sh
python3 tools/check_dashboard_api.py --base-url http://localhost:8000
```

state-aggregator가 cluster 안에만 있으면 별도 터미널에서 port-forward를 먼저 실행한다.

```bash
kubectl -n edge-orch port-forward svc/state-aggregator 8000:80
# 현재 로컬 클러스터처럼 service가 default namespace에 있으면:
# kubectl -n default port-forward svc/state-aggregator 8000:8000
```

## 1. Kubernetes node 상태

```bash
kubectl get nodes -o wide
```

정상 기준:

- Jetson node `etri-dev0001-jetorn`가 존재한다.
- Raspberry Pi node `etri-dev0002-raspi5`가 존재한다.
- control-plane/server node가 Ready다.
- Kubernetes Ready와 dashboard `node_ready`는 같은 의미가 아니다. dashboard `node_ready`는 state-aggregator가 Prometheus/node-exporter 기반 `node_health != unavailable`로 판단한 값이다.

## 2. mqttvirtual mapper 상태

```bash
kubectl get pods -A -o wide | grep -i mqttvirtual
```

정상 기준:

- Jetson/Raspberry Pi edge node에 할당된 mapper pod가 Running이다.
- mapper pod의 NODE column이 device 할당 node와 맞는다.

DMI socket mount 확인:

```bash
kubectl get pods -A -o wide | grep -i mqttvirtual
kubectl -n <mapper-namespace> describe pod <mapper-pod> | grep -A4 -B4 '/etc/kubeedge/dmi.sock'
```

MQTT connect/subscribe 로그 확인:

```bash
kubectl -n <mapper-namespace> logs <mapper-pod> --tail=200 | grep -Ei 'mqtt|connect|subscribe|factory/devices'
```

정상 기준:

- `/etc/kubeedge/dmi.sock` mount가 보인다.
- MQTT connect 또는 subscribe 관련 로그가 보인다.
- topic은 `factory/devices/{device-name}/telemetry` 경로를 사용한다.

## 3. Device CR / DeviceStatus 상태

```bash
kubectl get devices.devices.kubeedge.io -A
kubectl get devicestatuses.devices.kubeedge.io -A
kubectl get devices.devices.kubeedge.io -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName,MODEL:.spec.deviceModelRef.name'
```

정상 기준:

- Jetson device는 `etri-dev0001-jetorn`에 할당되어 있다.
- Raspberry Pi device는 `etri-dev0002-raspi5`에 할당되어 있다.
- DeviceStatus는 status-plane 보조 snapshot이다. DeviceStatus stale만으로 telemetry-enabled device의 healthy를 막으면 안 된다.

예상 nodeName:

| device 계열 | expected node |
|---|---|
| `env-device-*`, `vib-device-*`, `act-device-*`, `temp-device-01` | `etri-dev0001-jetorn` |
| `rpi-env-device-*`, `rpi-vib-device-*`, `rpi-act-device-*` | `etri-dev0002-raspi5` |

## 4. publisher 실행 검증

publisher는 각 edge node의 local mosquitto(`127.0.0.1:1883`)로 publish해야 한다.

Jetson device plan:

```bash
DEVICE_PLAN=jetson SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

Raspberry Pi device plan:

```bash
DEVICE_PLAN=rpi SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

단일 device:

```bash
DEVICE_FILTER=rpi-act-device-03 SIMULATION_MODE=stable python3 mappers/script/test_device.py
```

확인할 로그:

```text
[PUB] factory/devices/.../telemetry
```

정상 기준:

- publisher가 실행된 edge node의 `127.0.0.1:1883`으로 publish한다.
- publisher log에 `factory/devices/{device-name}/telemetry` publish 로그가 반복된다.
- wrong node에서 publisher를 실행하면 dashboard reason이 node/publisher/telemetry mismatch를 운영자가 해석할 수 있게 degraded 원인으로 보여야 한다.

## 5. InfluxDB 적재 검증

InfluxDB UI 또는 CLI에서 latest sample을 확인한다.

주의:

- InfluxDB UI의 `_start`와 `_stop`은 Flux query 조회 window이며 device start/stop 이벤트가 아니다.
- 실제 telemetry sample timestamp는 `_time`이다.
- Dashboard의 `telemetry_fresh`는 device-level latest sample 기준이다.
- property별 latest freshness를 보장하지 않는다.
- `ts`는 publisher payload에는 포함될 수 있지만 현재 dashboard freshness 판단용 DB push property가 아니다.

공통 latest query 예시:

```bash
kubectl exec -n telemetry influxdb-0 -- sh -lc 'influx query --org "$DOCKER_INFLUXDB_INIT_ORG" --token "$DOCKER_INFLUXDB_INIT_ADMIN_TOKEN" '\''
from(bucket:"device_telemetry")
  |> range(start:-30m)
  |> filter(fn:(r)=> r._measurement == "virtual_device_telemetry")
  |> last()
  |> keep(columns:["_time","_value","device_id","property"])
'\'''
```

계열별 확인 기준:

| device 계열 | 확인 property |
|---|---|
| `env-device-*`, `rpi-env-device-*` | `temperature`, `humidity` latest sample |
| `vib-device-*`, `rpi-vib-device-*` | `vibration` latest sample |
| `act-device-*`, `rpi-act-device-*` | `health` liveness row |

단일 actuator 예시:

```bash
kubectl exec -n telemetry influxdb-0 -- sh -lc 'influx query --org "$DOCKER_INFLUXDB_INIT_ORG" --token "$DOCKER_INFLUXDB_INIT_ADMIN_TOKEN" '\''
from(bucket:"device_telemetry")
  |> range(start:-30m)
  |> filter(fn:(r)=> r._measurement == "virtual_device_telemetry")
  |> filter(fn:(r)=> r.device_id == "rpi-act-device-03")
  |> filter(fn:(r)=> r.property == "health")
  |> last()
  |> keep(columns:["_time","_value","device_id","property"])
'\'''
```

정상 기준:

- `_time`이 현재 시각 기준 dashboard freshness threshold 안에 있다.
- act/rpi-act device는 latest property가 `health`로 확인된다.
- `ts`를 dashboard freshness 판단용 DB push property로 설명하지 않는다.

## 6. state-aggregator API 검증

port-forward:

```bash
kubectl -n edge-orch port-forward svc/state-aggregator 8000:80
# 현재 로컬 클러스터처럼 service가 default namespace에 있으면:
# kubectl -n default port-forward svc/state-aggregator 8000:8000
```

API 확인:

```bash
curl -s http://localhost:8000/state/nodes
curl -s http://localhost:8000/state/devices
curl -s http://localhost:8000/state/dashboard
curl -s http://localhost:8000/state/summary
curl -s http://localhost:8000/state/operator-assistant
curl -s http://localhost:8000/state/virtual-resources
```

자동 필드 확인:

```bash
python3 tools/check_dashboard_api.py --base-url http://localhost:8000
```

이 스크립트는 `/state/dashboard`와 `/state/virtual-resources`를 함께 검증한다.
자원증강 API가 없는 과거 배포만 확인할 때는 `--skip-virtual-resources`를 사용한다.

필수 device 필드:

```text
devices[].name
devices[].node_name
devices[].telemetry_enabled
devices[].telemetry_fresh
devices[].telemetry_last_seen_at
devices[].telemetry_property
devices[].device_status_fresh
devices[].mapper_running
devices[].node_ready
devices[].overall_status
devices[].reason
devices[].service_demo_group
devices[].service_connected
```

필수 KPI 필드:

```text
kpis.registered_device_count
kpis.live_device_count
kpis.telemetry_device_count
kpis.device_telemetry_ratio
kpis.fresh_telemetry_device_count
kpis.telemetry_freshness_ratio
kpis.fresh_device_status_count
kpis.device_status_freshness_ratio
kpis.operator_focus_count
kpis.service_bound_device_count
kpis.device_service_binding_ratio
```

정상 기준:

- telemetry-enabled device는 InfluxDB latest telemetry가 fresh하면 healthy 가능하다.
- DeviceStatus stale이어도 telemetry fresh이면 healthy일 수 있다.
- mapper가 없으면 reason이 mapper 문제를 설명한다.
- node가 unavailable이면 reason이 node 문제를 설명한다.
- InfluxDB latest sample이 없거나 stale이면 reason이 telemetry missing/stale을 설명한다.
- `/state/virtual-resources`는 AI HAT, GPU, cache 같은 보강 실행 자원을 Resource Profile 단위로 보여준다.
- Resource Profile은 실행 인스턴스가 0개여도 숨겨지지 않고 `configured_not_running`으로 표시될 수 있다.
- `observation_error`가 있으면 service resource 관측 실패로 해석하고, 센서 생성이나 자동 오프로딩 실패로 설명하지 않는다.

## 7. 검증 시나리오

### Scenario A: 정상 Jetson device

```bash
DEVICE_PLAN=jetson SIMULATION_MODE=stable python3 mappers/script/test_device.py
python3 tools/check_dashboard_api.py --base-url http://localhost:8000 --device env-device-01
```

정상 기준:

- Jetson device가 `healthy`다.
- `telemetry_fresh=true`
- `mapper_running=true`
- `node_ready=true`

### Scenario B: 정상 Raspberry Pi device

```bash
DEVICE_PLAN=rpi SIMULATION_MODE=stable python3 mappers/script/test_device.py
python3 tools/check_dashboard_api.py --base-url http://localhost:8000 --device rpi-env-device-01
```

정상 기준:

- `rpi-*` device가 `healthy`다.
- `telemetry_fresh=true`
- `mapper_running=true`
- `node_ready=true`

### Scenario C: publisher 미실행

절차:

1. 특정 device publisher를 실행하지 않는다.
2. freshness threshold가 지나기를 기다린다.
3. dashboard/API를 확인한다.

```bash
python3 tools/check_dashboard_api.py --base-url http://localhost:8000 --device <device-name>
```

정상 기준:

- `telemetry_fresh=false` 또는 latest sample missing
- `overall_status=degraded` 또는 `unavailable`
- `reason`이 telemetry missing/stale을 설명

### Scenario D: DeviceStatus stale but telemetry fresh

절차:

1. InfluxDB latest telemetry가 fresh한 device를 고른다.
2. DeviceStatus timestamp가 stale인 상태를 확인한다.
3. dashboard/API를 확인한다.

정상 기준:

- `telemetry_fresh=true`
- `device_status_fresh=false`
- 최종 status는 `healthy` 가능
- UI에서는 DeviceStatus stale을 보조 신호로만 표시

### Scenario E: mapper 문제

read-only 확인만 수행한다.

```bash
kubectl get pods -A -o wide | grep -i mqttvirtual
python3 tools/check_dashboard_api.py --base-url http://localhost:8000
```

정상 기준:

- mapper pod가 없는 node의 device는 `mapper_running=false`
- reason이 `assigned mapper is not running` 또는 mapper 문제를 설명

### Scenario F: act/rpi-act liveness

```bash
DEVICE_FILTER=rpi-act-device-03 SIMULATION_MODE=stable python3 mappers/script/test_device.py
python3 tools/check_dashboard_api.py --base-url http://localhost:8000 --device rpi-act-device-03
```

정상 기준:

- InfluxDB latest property가 `health`
- dashboard `telemetry_property=health`
- dashboard freshness 판단이 `health` row 기준으로 설명됨
- `ts`는 dashboard freshness 판단용 DB push property가 아님

### Scenario G: 자원증강형 가상디바이스 표시

자원증강형 가상디바이스는 가상 센서가 아니라 물리 디바이스의 부족한 AI 연산/GPU/스토리지/cache를 보강하는 실행 자원이다.

```bash
curl -s http://localhost:8000/state/virtual-resources
curl -s http://localhost:8000/state/virtual-resources/vd-aihat-inference/twin
curl -s http://localhost:8000/state/augmentation-resources
curl -s http://localhost:8000/state/device-augmentations
python3 tools/check_resource_augmentation_scenario.py --base-url http://localhost:8000
```

정상 기준:

- `mode=read_only`
- `scope=resource_augmentation_virtual_devices`
- `resources[]`에 AI HAT/GPU/cache Resource Profile이 표시됨
- 각 profile에 `desired_instances`, `observed_instances`, `free_instances`, `allocated_instances`가 표시됨
- `jetson-vision-inspection` 시나리오에서 `jetson-gpu-storage-augmentation`이 `Ready`
- `selectedResources`에 `vd-x86-gpu-inference`, `vd-storage-cache`가 표시됨
- 두 `AugmentationResource`가 `Available`이고 endpoint ready임
- 실행 중인 runtime이 없으면 `status=configured_not_running`, `twin.binding_state=not_running`
- 관측 실패 시에도 registry profile은 표시되고 `observation_error`로 원인이 드러남
- 이 검증 중 Kubernetes 배포, MQTT command publish, Device CR 수정, runtime migration/offloading을 하지 않음

## 실패 시 원인 분리

| 증상 | 먼저 볼 곳 | 해석 |
|---|---|---|
| Device CR 없음 | `kubectl get devices.devices.kubeedge.io -A` | 등록/manifest 문제 |
| Device nodeName 불일치 | Device CR custom-columns | publisher 실행 node와 Device 할당 node mismatch 가능 |
| mapper Running 아님 | mapper pod, DMI socket mount, logs | mapper 또는 edge node 문제 |
| publisher PUB 로그 없음 | `test_device.py` stdout | publisher/MQTT broker 문제 |
| InfluxDB latest 없음 | Influx query | MQTT->mapper->DB 경로 문제 |
| DeviceStatus stale | DeviceStatus timestamp | status-plane 보조 경고 |
| telemetry fresh + DeviceStatus stale | dashboard/API | healthy 가능, status-plane 별도 점검 |
| node_ready=false | `/state/nodes`, Prometheus/node-exporter | dashboard 기준 node health 문제 |
| virtual resource profile 없음 | `/state/virtual-resources` | registry/API 연결 문제 |
| virtual resource observed_instances=0 | `/state/virtual-resources`, service resource profiles | 보강 자원 registry는 있으나 runtime 미실행 가능 |
| virtual resource observation_error | `/state/virtual-resources`, Prometheus/service resource observation | 관측 실패. 자동 오프로딩 실패로 해석하지 않음 |
