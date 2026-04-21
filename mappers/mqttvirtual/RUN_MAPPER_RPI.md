# Edge Mapper 실행법 (이기종 공통)

이 문서는 라즈베리파이/Jetson/x86 등 이기종 노드에서 `mqttvirtual` 매퍼를 실행하는 방법을 정리한다.

## 1) 가장 빠른 수동 실행 (권장)

현재 노드 아키텍처를 먼저 확인한다.

```bash
uname -m
```

아키텍처별 권장 바이너리 이름:
- `aarch64` -> `mqttvirtual-arm64`
- `x86_64` -> `mqttvirtual-amd64`

```bash
cd /home/etri/mqttvirtual
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o mqttvirtual-arm64 ./cmd
pkill -f 'mqttvirtual-arm64 --config-file ./config.yaml' || true
sudo ./mqttvirtual-arm64 --config-file ./config.yaml --v 4 2>&1 | tee mapper.log
```

x86_64 노드는 아래처럼 `GOARCH=amd64`, 바이너리명 `mqttvirtual-amd64`로 바꿔 실행한다.

설명:
- 1줄: 바이너리 빌드
- 2줄: 기존 동일 실행 프로세스 정리
- 3줄: foreground 실행 + 로그 저장

## 2) register 스크립트 사용

파일: `register_mapper_rpi.sh`

이 스크립트는 호스트 아키텍처를 자동 감지해(`arm64`/`amd64`/`arm`) 빌드한다.

초기 점검:
```bash
cd /home/etri/jinuk/mappers/mqttvirtual
./register_mapper_rpi.sh check
```

빌드:
```bash
./register_mapper_rpi.sh build
```

포그라운드 실행(수동 3줄과 유사):
```bash
./register_mapper_rpi.sh run-fg
```

백그라운드 실행:
```bash
./register_mapper_rpi.sh start
```

상태 확인:
```bash
./register_mapper_rpi.sh status
```

중지:
```bash
./register_mapper_rpi.sh stop
```

## 3) 자주 확인할 포인트

- edgecore DMI 소켓 존재: `/etc/kubeedge/dmi.sock`
- mapper 소켓 경로: `/etc/kubeedge/mqttvirtual.sock`
- 로그 파일:
  - 수동 실행: `mapper.log`
  - register 스크립트 기본: `mapper.log`

## 4) 빌드 에러 시 (api/mapper-framework 경로)

`reading ../mapper-framework/go.mod: no such file or directory` 오류가 나면,
자동 탐색이 현재 폴더 구조를 못 맞춘 경우다.

아래처럼 경로를 명시해서 실행하면 바로 해결된다.

```bash
cd /home/etri/edge-ai-workspace/mappers/mqttvirtual
API_DIR=/home/etri/edge-ai-workspace/api \
FRAMEWORK_DIR=/home/etri/edge-ai-workspace/mapper-framework \
./register_mapper_rpi.sh build
```
