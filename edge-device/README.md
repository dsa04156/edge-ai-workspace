# edge-device PoC

이 디렉터리는 과거 KubeEdge `DeviceModel`/`Device` manifest와 MapperFramework 기반 물리 디바이스 연동 실험을 보존하는 legacy/reference 경로다. 현재 물리 디바이스의 inventory, state, telemetry, command를 관리하거나 복구하는 경로가 아니다.

현재 권위 경로:

```text
physical device
  -> Protocol Adapter -> edge-telemetry-agent -> SQLite outbox
  -> HTTPS ingest gateway -> EdgeX Core Data / PostgreSQL
  -> AI services / storage / state-aggregator / dashboard
```

- inventory와 state의 원본은 EdgeX Core Metadata의 Device Profile/Device다.
- telemetry의 원본은 EdgeX Core Data Event/Reading이며 freshness는 Event `origin`을 기준으로 계산한다.
- 현재 command 실행은 비활성이다. 활성화 시 protocol endpoint를 소유한 Adapter와 Device Profile command 계약을 별도 검증한다.
- KubeEdge는 edge node와 workload 관리 및 선택적 placement 진단에만 사용한다. `DeviceStatus`를 물리 availability의 병행 plane이나 EdgeX 장애 fallback으로 사용하지 않는다.
- `mqttvirtual`, MapperFramework, mapper direct-to-InfluxDB 경로는 legacy test/integration 자료다.

## Layout

- `models/`: legacy/reference KubeEdge DeviceModel manifests
- `live/`: 과거 Arduino-backed KubeEdge Device manifest 자료. 이름과 관계없이 현재 physical inventory는 이 디렉터리가 아니라 EdgeX Core Metadata에서 관리한다.
- `devices.yaml`, `devices-rpi.yaml`: legacy virtual Device manifest 출력 대상이며 current manifest가 아니다.
- `scripts/generate_devices.py`: legacy virtual Device manifest generator. 기본 실행 시 Device YAML을 생성하지 않는다.

## Legacy virtual Device generation

명시적인 legacy 호환성 검증에서만 아래 generator를 사용한다. 생성된 manifest를 current physical inventory 또는 status/control plane으로 해석하지 않는다.

```bash
ENABLE_LEGACY_VIRTUAL_DEVICES=1 python3 /home/etri/jinuk/edge-device/scripts/generate_devices.py > /tmp/legacy-devices.yaml
ENABLE_LEGACY_VIRTUAL_DEVICES=1 DEVICE_PLAN=rpi python3 /home/etri/jinuk/edge-device/scripts/generate_devices.py > /tmp/legacy-devices-rpi.yaml
```

적용이 필요한 legacy test에서는 먼저 server-side dry-run으로 대상 이름을 확인한다.

```bash
kubectl apply --dry-run=server -f /tmp/legacy-devices.yaml
```

이 절차는 EdgeX 등록이나 current cutover 절차가 아니다.

## Current EdgeX model

Core Metadata Device를 조회하는 consumer는 다음 필드를 기준으로 physical inventory와 state를 표현한다.

- `name`
- `profileName`
- `serviceName`
- `protocols`
- `adminState`
- `operatingState`
- 선택적 `tags`/properties 기반 node diagnostic 정보

Core Data telemetry는 Event의 `deviceName`, `sourceName`, `origin`과 각 Reading의 `valueType`/typed value를 보존한다. KubeEdge `DeviceStatus` summary나 mapper timestamp로 이 값을 복제하거나 대체하지 않는다.

Kubernetes Node/Pod 정보는 workload 배치와 진단에 표시할 수 있지만 EdgeX `adminState`, `operatingState`, Core Data Event freshness로 계산한 물리 디바이스 availability를 변경하지 않는다.

## Delivery boundary

현재 repository에서 전달된 physical cutover 코드 범위는 loopback Protocol Adapter, direct-mode agent, SQLite/HTTPS plane과 EdgeX-backed aggregator/dashboard다. `sensehat-001`은 교체 가능한 검증 fixture이며 현재 Jetson/Arduino MQTT workload는 없다. 이는 repository artifact 범위이며 live cluster 배포 완료를 의미하지 않는다.

Serial, Modbus, OPC-UA, RTSP는 각각 별도 migration gate를 통과해야 하는 후속 protocol wave다. 제거된 과거 Serial JSON publisher prototype은 EdgeX Serial Device Service 또는 Serial wave 완료 근거로 사용하지 않는다.
