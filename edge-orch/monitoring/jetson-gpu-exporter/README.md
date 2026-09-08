# Jetson GPU 사용률 수집

2026-09-08 사용자 설치 요청 범위는 Nano `etri-dev0001-jetorn`과 AGX
`etri-dev0005-jetagx`의 GPU 사용률을 Prometheus와 dashboard에 연결하는 것이다.
서버의 기존 DCGM exporter는 변경하지 않는다.

## 방식과 권한

L4T 36.4.7 / 39.2.1 두 장비에서 읽기 가능한 GPU driver sysfs load를 사용한다.
처음 검토한 tegrastats wrapper 대신 버전별 바이너리 의존성이 없는 Python 표준
라이브러리 exporter를 사용한다. NVIDIA 문서의 raw load / 10 = percent 규칙에 따라
raw / 1000을 ratio로 제공한다.
[공식 측정 정의](https://docs.nvidia.com/jetson/archives/r36.2/DeveloperGuide/SD/Clocks.html).

허용된 hostPath는 `/sys/devices/platform/bus@0/17000000.gpu/load` 파일 하나이며
readOnly mount다. root, privileged, hostPID, Kubernetes API token을 사용하지 않는다.
GPU 작업 배치나 GPU time-slicing slot을 소비하지 않으며 frequency/power 설정을 바꾸지 않는다.
9401 hostNetwork HTTP는 읽기 전용 metric과 health만 제공한다.

## 배포 소유권

기존 `edge-orch/monitoring/dcgm-exporter.yaml`처럼 운영자가 Git의 Kustomize를 적용한다.
Argo CD Application 소유 리소스를 수동 덮어쓰지 않는다. 신규 exporter 리소스만 생성한다.

```bash
kubectl apply -k edge-orch/monitoring/jetson-gpu-exporter
kubectl -n kube-system rollout status ds/jetson-gpu-exporter
```

ServiceMonitor는 기존 Prometheus release selector를 사용한다. `instance`를 노드 IP:9100으로
설정해 기존 node-exporter CPU·RAM identity와 합치며 scrape 주소는 9401을 유지한다.
Aggregator 코드는 기존 GitOps 배포 경로로 반영한다.

## 데이터 계약

- `jetson_gpu_utilization_ratio`: 0..1. 읽기 실패·범위 오류에서는 시계열을 생략한다.
- `jetson_gpu_collector_success`: 이번 읽기 성공 1 / 실패 0.
- `/healthz`는 exporter 생존이며 GPU 측정 성공과 별개다.
- 매 scrape에 sysfs를 읽는다. 마지막 성공값을 현재 값처럼 재사용하지 않는다.
- Aggregator는 collector_success=1 및 scrape up=1인 Jetson 지표만 받아 DCGM과 결합한다.
- GPU 메모리·프로세스별 할당·온도·전력은 이번 exporter의 측정 범위가 아니다.
  Jetson 공유 RAM을 별도 GPU VRAM 사용량으로 표시하지 않는다.

## 검증과 제거

`python3 -m unittest -q`는 0/최대/중간값 변환과 누락·오류에서 0을 만들지 않음을 검증한다.
실장비 검증은 `/metrics` → Prometheus query → `/state/nodes` → dashboard 순서다.
롤백은 이전 aggregator digest로 Git revert하고 exporter는 위 경로에
`kubectl delete -k`를 적용한다. 서버 DCGM과 센서 Device Service에는 영향이 없다.

배포 이미지의 ARM64 manifest를 확인해 `python:3.11-slim@sha256:6c5ae9d998f4cc06f892f428d7af53a566c24ad0dc29fa572696b647cf2762a7`로 고정했다.
내부 registry에도 동일 digest를 보관했지만 AGX의 HTTP registry 미허용 정책을
변경하지 않고 공식 HTTPS registry를 사용한다. exporter Python 의존성 설치는 없다.
