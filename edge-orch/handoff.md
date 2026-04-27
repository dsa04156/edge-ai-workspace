# Handoff

## Current Focus

현재 작업의 중심은 KubeEdge `mqttvirtual` mapper 기반 가상 센서 디바이스 실험이다.

핵심 목표:
- MQTT telemetry 수신 경로 검증
- `DeviceModel` / `Device` / `DeviceStatus` 연동 검증
- 대표 상태(`DeviceStatus`)와 실측 telemetry 분리
- 이후 20개 디바이스 병렬 실험으로 확장

## Current State

확인된 것:
- 단일 디바이스 `temp-device-01` 기준 `DeviceStatus.status.twins.reported` 반영은 검증했다.
- `mqttvirtual` 수정본은 `/home/etri/jinuk/mappers/mqttvirtual` 기준으로 관리한다.
- Jetson 실제 실행 경로는 `/home/etri/mqttvirtual` 이고, 주요 수정 내용은 반영해 두었다.
- `stream`이 아니라 `non-stream` 센서 상태값 실험이 맞다는 방향으로 정리했다.

현재 설계:
- telemetry:
  - `temperature`
  - `humidity`
  - `vibration`
- representative status (`DeviceStatus`):
  - `sampling_interval`
  - `alarm`
  - `power`
  - `mode`
  - device connectivity state

현재 `DeviceStatus` 보고 정책:
- 즉시 report 제거
- `5초` flush loop
- changed-only
- 동일 값 재보고 금지

## Important Changes

### 1. `mqttvirtual` mapper

기준 소스:
- [mappers/mqttvirtual](/home/etri/jinuk/mappers/mqttvirtual)

주요 수정:
- import 경로를 `github.com/kubeedge/mqttvirtual` 로 통일
- `stream` / `non-stream` build tag 분리
- `DeviceStatus` 대상 property allowlist 적용
- `runEventTwinReporter()` 를 즉시 report 에서 `5초 flush + changed-only` 로 변경

핵심 파일:
- [mappers/mqttvirtual/device/device.go](/home/etri/jinuk/mappers/mqttvirtual/device/device.go)
- [mappers/mqttvirtual/device/devicetwin.go](/home/etri/jinuk/mappers/mqttvirtual/device/devicetwin.go)
- [mappers/mqttvirtual/device/devicestatus.go](/home/etri/jinuk/mappers/mqttvirtual/device/devicestatus.go)
- [mappers/mqttvirtual/driver/driver.go](/home/etri/jinuk/mappers/mqttvirtual/driver/driver.go)
- [mappers/mqttvirtual/config.yaml](/home/etri/jinuk/mappers/mqttvirtual/config.yaml)

Jetson 실행 기준:
```bash
cd /home/etri/mqttvirtual
CGO_ENABLED=0 go build -o mqttvirtual-arm64 ./cmd
pkill -f 'mqttvirtual-arm64 --config-file ./config.yaml' || true
sudo ./mqttvirtual-arm64 --config-file ./config.yaml --v 4 2>&1 | tee mapper.log
```

### 2. `edge-device` 디바이스 구성

기준 경로:
- [edge-device/models](/home/etri/jinuk/edge-device/models)
- [edge-device/devices.yaml](/home/etri/jinuk/edge-device/devices.yaml)
- [edge-device/scripts/generate_devices.py](/home/etri/jinuk/edge-device/scripts/generate_devices.py)
- [edge-device/scripts/deploy.sh](/home/etri/jinuk/edge-device/scripts/deploy.sh)

현재 모델:
- `virtual-env-model`
- `virtual-vib-model`
- `virtual-act-model`

생성된 디바이스:
- `env-device-01 ~ 08`
- `vib-device-01 ~ 06`
- `act-device-01 ~ 06`

배포 스크립트 동작:
- `models/` 적용
- `devices.yaml` 적용
- `k8s/`는 적용하지 않음

즉 현재 `deploy.sh`는 logical device CR만 배포한다.
가상 센서 publisher 컨테이너는 별도 실행 전제로 본다.

## Known Issues

1. `DeviceStatus` CR 존재 여부만으로 연결 확인이 안 된다.
- 값 변화와 `resourceVersion` 증가를 같이 봐야 한다.

2. edgecore 내부 propagation latency 가 있다.
- mapper 수신 즉시와 CR 반영 시각이 다를 수 있다.

3. 테스트용 publisher 스크립트는 telemetry/status 해석을 섞기 쉬웠다.
- [mappers/script/test_device.py](/home/etri/jinuk/mappers/script/test_device.py)
- 현재 모델 key 에 맞게 수정했지만, 대표 상태는 자주 바뀌지 않게 운용하는 것이 맞다.

4. `Platform-Service`는 통합 git 대상에서 제외했다.

## Recommended Next Steps

1. Jetson에서 `mqttvirtual` 재빌드/재기동
- 최신 `5초 flush + changed-only` 정책이 실제 바이너리에 반영되었는지 확인

2. `edge-device/scripts/deploy.sh` 재실행
- 대표 상태만 `reportToCloud: true` 인 새 `devices.yaml` 적용

3. 대표 상태만 바꿔서 검증
- `power`, `mode`, `alarm`, `sampling_interval` 변경 시
- `DeviceStatus.status.twins.reported` 와 `resourceVersion` 확인

4. telemetry 경로 별도 검증
- `temperature`, `humidity`, `vibration` 는 MQTT 수신 로그/consumer 기준으로 확인
- `DeviceStatus`에 안 올라가도 정상으로 간주

5. 20개 병렬 검증
- 대표 상태만 `DeviceStatus` 반영되는지 확인
- telemetry는 별도 경로로 관측
- edgecore limiter 재발 여부 확인

## Reference

상세 경과 정리:
- [edge-orch/docs/통합문서.md](/home/etri/jinuk/edge-orch/docs/통합문서.md)
