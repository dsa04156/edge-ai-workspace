# edge-device PoC

KubeEdge 기반 mixed-device 제어·관리 플랫폼에서 DeviceModel/Device manifest를 관리하기 위한 디렉터리다.

현재 운영 기준:
- live PoC의 기본 Device CR은 물리/Arduino/EdgeX-backed 등록 경로를 기준으로 한다.
- 과거 `env-device-*`, `vib-device-*`, `act-device-*`, `rpi-*-device-*` 가상 Device는 live 클러스터에서 제거된 legacy test 대상이다.
- MapperFramework는 raw telemetry export engine이 아니라 KubeEdge control/status summary adapter로 유지한다.
- raw telemetry ingestion은 향후 EdgeX 별도 plane에서 담당한다.

## Layout

- `models/`: legacy/공통 DeviceModel manifests
- `live/`: 현재 클러스터에 등록된 Arduino-backed live Device manifests. 새 실디바이스 등록은 이 디렉터리에 Device YAML을 추가한다.
- `devices.yaml`, `devices-rpi.yaml`: live manifest로 유지하지 않는다. legacy virtual Device manifest를 저장하지 않는다.
- `scripts/generate_devices.py`: legacy virtual Device manifest generator. 기본 실행 시 Device YAML을 생성하지 않는다.

## Legacy virtual Device generation

가상 Device를 다시 만들면 live dashboard/device 목록에 `env-device-*`, `vib-device-*`, `act-device-*`, `rpi-env-device-*`, `rpi-vib-device-*`, `rpi-act-device-*`가 재생성된다.
따라서 명시적인 legacy test가 아니면 아래 명령을 사용하지 않는다.

```bash
ENABLE_LEGACY_VIRTUAL_DEVICES=1 python3 /home/etri/jinuk/edge-device/scripts/generate_devices.py > /tmp/legacy-devices.yaml
ENABLE_LEGACY_VIRTUAL_DEVICES=1 DEVICE_PLAN=rpi python3 /home/etri/jinuk/edge-device/scripts/generate_devices.py > /tmp/legacy-devices-rpi.yaml
```

live 클러스터에 적용하기 전에는 반드시 대상 Device 이름을 확인한다.

```bash
kubectl apply --dry-run=server -f /tmp/legacy-devices.yaml
```

## MapperFramework / EdgeX split

MapperFramework 리팩토링 목표는 raw telemetry export engine 확장이 아니라 KubeEdge control/status summary 연동이다.
향후 `temperature`, `humidity`, `vibration`, `acceleration_x/y/z`, `waveform` 같은 raw telemetry ingestion은 EdgeX 기반 별도 plane으로 분리한다.

Current split:
- `temperature`, `humidity`, `vibration`, `acceleration_x/y/z`, `waveform`: MapperFramework 주 경로에서 제외, EdgeX telemetry ingestion plane으로 이관 예정
- `health`, `severity`, `command_state`, `online/offline`, `control_response`, `alarm_latched`, `power`, `mode`, `sampling_interval`: DeviceStatus summary
- raw telemetry field는 DeviceStatus summary로 올리지 않는다.

## Apply Models

DeviceModel은 공통/legacy compatibility 목적으로 남아 있을 수 있다. 실제 Device CR 생성과는 별개다.

```bash
kubectl apply -f /home/etri/jinuk/edge-device/models/
```

## Current live expectation

현재 live 클러스터에서 legacy virtual Device가 없어야 한다.
확인 예:

```bash
kubectl get device -n default --no-headers | grep -E '^(env|vib|act|rpi-env|rpi-vib|rpi-act)-device-' || true
```

위 명령이 비어 있으면 정상이다.
