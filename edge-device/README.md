# edge-device PoC

KubeEdge 기반 mixed-device 제어·관리 플랫폼에서 가상 디바이스를 컨테이너 단위로 구현하기 위한 1차 PoC 작업 디렉터리다.

현재 목표:
- 가상 디바이스 20개 병렬 실행
- MQTT 기반 telemetry / command 경로 검증
- KubeEdge `DeviceModel` / `Device` / `DeviceStatus` 반영 검증
- 이후 물리/가상 혼합 디바이스 관리로 확장

## Layout

- `models/`: DeviceModel manifests
- `k8s/`: StatefulSet manifests for virtual devices
- `virtual-device/`: shared container image source
- `scripts/generate_devices.py`: generate 20 Device manifests

## Device Plan

- `env-device-01` ~ `env-device-08`
- `vib-device-01` ~ `vib-device-06`
- `act-device-01` ~ `act-device-06`

Models:
- `virtual-env-model`
- `virtual-vib-model`
- `virtual-act-model`

Runtime:
- shared image: `192.168.0.56:5000/virtual-device:latest`
- `StatefulSet` 3개
- edge broker: `HOST_IP:1883`
- topic prefix: `factory/devices`

## Generate Device YAML

```bash
python3 /home/etri/jinuk/edge-device/scripts/generate_devices.py > /home/etri/jinuk/edge-device/devices.yaml
```

Raw telemetry properties use KubeEdge Mapper Framework's `pushMethod.dbMethod.influxdb2` path.

Current split:
- `temperature`, `humidity`, `vibration`: `reportToCloud: false`, stored to InfluxDB
- `health`, `severity`, `alarm_latched`, `power`, `mode`, `sampling_interval`: reported as DeviceStatus summary
- Device `status.reportToCloud`: `false`, to avoid high-rate `ReportDeviceStates`

InfluxDB defaults used by the generator:

```bash
INFLUX_URL=http://influxdb.telemetry.svc.cluster.local:8086
INFLUX_ORG=edgeai
INFLUX_BUCKET=device_telemetry
INFLUX_MEASUREMENT=virtual_device_telemetry
```

If the mapper runs as a host process instead of a Kubernetes Pod, generate with an address reachable from the edge node:

```bash
INFLUX_URL=http://10.100.80.4:8086 \
python3 /home/etri/jinuk/edge-device/scripts/generate_devices.py > /home/etri/jinuk/edge-device/devices.yaml
```

The mapper InfluxDB client reads the token from the `TOKEN` environment variable. For a Pod-based mapper, create a secret in the mapper namespace:

```bash
kubectl create secret generic influxdb-token -n default \
  --from-literal=token=edgeai-super-token-change-me
```

For a host-run mapper:

```bash
sudo env TOKEN=edgeai-super-token-change-me ./mqttvirtual-arm64 --config-file ./config.yaml --v 4
```

## Apply Models

```bash
kubectl apply -f /home/etri/jinuk/edge-device/models/
```

## Apply Devices

```bash
kubectl apply -f /home/etri/jinuk/edge-device/devices.yaml
```

## Apply StatefulSets

The manifests use `192.168.0.56:5000/virtual-device:latest`.

```bash
kubectl apply -f /home/etri/jinuk/edge-device/k8s/
```

## Verified So Far

- `temp-device-01` 단일 디바이스는 `DeviceStatus` 기준 reported 값 반영을 확인했다.
- `virtual-device` 공통 이미지를 edge registry(`192.168.0.56:5000`)에 push하고, Jetson에서 pull 가능한 상태로 맞췄다.
- `StatefulSet` 3개를 통해 `env` / `vib` / `act` 가상 디바이스 컨테이너를 실제로 기동했다.
- 대표 telemetry topic 확인:
  - `factory/devices/env-device-01/telemetry`
  - `factory/devices/vib-device-01/telemetry`
  - `factory/devices/act-device-01/telemetry`

## Current Caveat

20개 병렬 인스턴스 전체에 대해 `DeviceStatus.status.twins` 가 안정적으로 채워지지는 않았다.

현재 분석 결과:
- 가상 디바이스 컨테이너의 MQTT publish는 정상이다.
- KubeEdge `Device` / `DeviceStatus` CR 생성도 정상이다.
- 남은 병목은 `mqttvirtual` mapper 구현 쪽이다.

대표 증상:
- `broken pipe`
- `use of closed network connection`
- `deviceModel ... not found`
- `connect refused`

즉, 현재 단계는 "인프라/배포/가상 디바이스 런타임" 은 준비되었고, "다중 디바이스용 mapper 안정화" 가 다음 핵심 작업이다.
