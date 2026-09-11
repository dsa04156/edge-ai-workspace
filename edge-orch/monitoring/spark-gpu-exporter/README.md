# Spark GPU 수집기

2026-09-11 사용자 설치 승인: Spark `etri-ser0003-cg0ms0`의 GPU 온도·사용률·전력을
Prometheus와 대시보드에 연결한다. 기존 amd64 DCGM DaemonSet은 `gpu.platform=server`
라벨과 amd64 아키텍처를 동시에 요구하므로 ARM64 Spark에는 라벨만 추가해도 배포되지 않는다.

## 라벨로 자동 배포

운영자가 Git의 이 Kustomize를 적용한다. 기존 Jetson/DCGM 수집기와 같은 수동 배포 소유권이며
Argo CD 소유 리소스를 덮어쓰지 않는다. 대시보드 backend는 기존 Argo CD 경로다.

```bash
rtk proxy kubectl apply -k edge-orch/monitoring/spark-gpu-exporter
rtk proxy kubectl label node etri-ser0003-cg0ms0 monitoring.jinuk.io/gpu-collector=spark-nvidia-smi
rtk proxy kubectl -n kube-system rollout status ds/spark-gpu-exporter
```

이후 Linux/ARM64 노드에 위 라벨을 붙이면 DaemonSet이 자동 배포한다. 해당 노드는
GB10 드라이버와 `nvidia-spark` RuntimeClass의 NVIDIA runtime 설정이 준비돼 있어야 한다.
라벨은 수집기 배치만 선택하며 드라이버를 설치하지 않는다. 임의 ARM 장비에 적용하지 않는다.
Spark 수집 중지만 필요하면 해당 라벨을 제거한다:

```bash
rtk proxy kubectl label node etri-ser0003-cg0ms0 monitoring.jinuk.io/gpu-collector-
```

## 측정과 권한

NVIDIA runtime이 제공하는 `nvidia-smi`에 고정 읽기 쿼리만 실행한다. GPU 설정 쓰기,
GPU 리소스 예약, hostPath, hostNetwork, privileged, root, Kubernetes token을 사용하지 않는다.
비root 사용자, 읽기 전용 rootfs, utility capability로 실행한다. 9402 Pod endpoint는
`/metrics`와 `/healthz`만 제공하며 매 scrape에 새 값을 읽고 최대 3초로 제한한다.

- `spark_gpu_temperature_celsius`: GPU 온도 °C
- `spark_gpu_utilization_percent`: GPU 사용률 0~100%
- `spark_gpu_power_watts`: GPU 전력 W (서버 전체 소비전력이 아님)
- `spark_gpu_collector_success`: 이번 쿼리가 유효 지표를 반환하면 1, 실패하면 0

미지원 필드, 비유한 값과 범위 오류는 시계열을 생략한다. 이전 성공값을 재사용하지 않는다.
`/healthz`와 Prometheus `up`은 수집기 생존/스크랩 성공이며 GPU 측정 성공과 다르다.
Aggregator는 success=1 및 up=1인 Spark 지표만 결합한다. instance는 노드 IP:9100으로
relabel하여 node-exporter의 CPU·시스템 RAM과 같은 노드로 연결한다.

Spark 실측에서 `memory.used`/`memory.free`는 `[N/A]`다. UMA 시스템의 GPU 전용 framebuffer
사용량 미지원은 [NVIDIA 공식 안내](https://docs.nvidia.com/dgx/dgx-spark/known-issues.html)에
설명돼 있다. 시스템 RAM이나 프로세스별 모델 메모리를 GPU 전용 VRAM 값으로 대체하지 않는다.

## 검증

`rtk proxy python3 -m unittest -q`를 이 디렉터리에서 실행한다. 정상/유휴 값,
미지원·NaN·범위 오류와 명령 실패/타임아웃 후 이전 값 미재사용을 검증한다.
운영 검증 순서는 label→DaemonSet Ready→/metrics→Prometheus→/state/nodes→화면이다.
검증 근거는 `results/2026-09-11.json`에 보관한다.

## 운영 반영 결과 (2026-09-11 15:59 KST)

- 라벨 전 DaemonSet desired=0 → Spark 라벨 후 desired=1/Ready=1, restart=0.
- Prometheus `up=1`, collector_success=1; GPU 온도 37°C, 유휴 GPU 사용률 0%, GPU 전력 약 4.5W.
- 실제 PromQL에서 수집 실패 또는 scrape 실패 조건이면 GPU 값이 제외되는지 확인했다.
  읽기 전용 쿼리 변환 검증으로 운영 수집기는 중지하지 않았다.
- `/state/nodes` Spark에 GPU 온도·사용률·전력 연결, 미지원 VRAM 생략.
- 1440px 운영 화면에서 3단계 지도 및 노드 상태 GPU 온도 37.0°C·사용률 0.0% 확인,
  브라우저 오류·경고 0. Argo CD Synced/Healthy와 Ready Pod 소스 해시 일치.
- exporter 3건 + aggregator Prometheus/normalizer 12건 통과. 기존 EdgeX 센서 Pod 2개 Ready 유지.
- 이번 작업은 GPU 계측 설치 검증이며 AI 서비스 부하·증강 승인을 실행하지 않았다.
