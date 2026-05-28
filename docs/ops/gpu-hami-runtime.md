# HAMi GPU runtime 운영 메모

이 문서는 x86 GPU 서버의 GPU 공유/스케줄링 기반으로 설치된 HAMi 상태를 기록한다.
현재 PoC에서 HAMi는 GPU 자원 운영 보조 계층이며, KubeEdge `DeviceStatus`나 raw telemetry 경로가 아니다.

## 현재 설치 상태

확인일: 2026-05-28

HAMi는 `kube-system` namespace에 Helm release로 설치되어 있다.

```text
release: hami
namespace: kube-system
chart: hami-2.9.0
app version: 2.9.0
```

실행 중인 주요 리소스:

```text
hami-scheduler       Deployment  1/1 Running
hami-device-plugin   DaemonSet   gpu=on node 대상, 2/2 Running
```

서비스:

```text
hami-device-plugin-monitor   NodePort 31992
hami-scheduler               NodePort 31998, 31993
```

현재 HAMi device plugin이 동작하는 GPU 서버:

| 노드 | 역할 | GPU label | HAMi 관점 |
|---|---|---|---|
| `etri-ser0001-cg0msb` | control-plane / cloud GPU server | `gpu=on`, `gpu.platform=server` | HAMi device plugin 대상 |
| `etri-ser0002-cgnmsb` | worker / cloud GPU server | `gpu=on`, `gpu.platform=server`, `accelerator=nvidia-gpu` | HAMi device plugin 대상 |

현재 Kubernetes allocatable 기준으로 두 서버 모두 `nvidia.com/gpu=10`으로 노출된다.
이는 물리 GPU 1장을 HAMi가 vGPU 단위로 나누어 스케줄링할 수 있게 만든 상태로 해석한다.

```text
etri-ser0001-cg0msb nvidia.com/gpu=10
etri-ser0002-cgnmsb nvidia.com/gpu=10
```

## PoC 내 역할

HAMi는 다음 용도로 본다.

- x86 GPU 서버의 GPU 자원 공유/분할 스케줄링
- 여러 추론/실험 Pod가 GPU를 독점하지 않고 나눠 쓰는 기반
- GPU stage 배치 실험 또는 과거 runtime replanning 실험을 재현할 때 사용할 수 있는 자원 계층
- DCGM exporter / Prometheus / state-aggregator / Grafana와 함께 GPU 운영 가시성을 보강하는 기반

HAMi가 직접 담당하지 않는 것:

- KubeEdge DeviceStatus 생성 또는 수정
- raw sensor telemetry ingestion
- MapperFramework 데이터 경로
- dashboard의 device healthy/degraded 판단
- workflow runtime replanning 자체

즉, HAMi는 GPU 자원 제공/스케줄링 계층이고, 실제 상태 관측은 DCGM exporter와 Prometheus/state-aggregator 경로로 유지한다.

## 현재 관측 경로와의 관계

현재 GPU 관측 흐름은 다음과 같이 유지한다.

```text
x86 GPU server
  -> HAMi device plugin / scheduler: GPU 공유 자원 노출
  -> DCGM exporter: GPU 사용률/메모리/온도/전력 metric 노출
  -> Prometheus
  -> state-aggregator Node.raw_metrics
  -> dashboard/Grafana
```

주의:

- HAMi가 `nvidia.com/gpu` allocatable 값을 10으로 노출하더라도, dashboard에서 GPU 사용률은 DCGM exporter metric을 기준으로 본다.
- HAMi resource count와 DCGM GPU utilization은 서로 다른 의미다.
- GPU 사용률/온도/전력은 node observability data로만 다루고, KubeEdge DeviceStatus에는 넣지 않는다.

## 점검 명령

HAMi release 확인:

```bash
helm list -n kube-system | grep -i hami
```

HAMi Pod/Service 확인:

```bash
kubectl get all -n kube-system | grep -Ei 'hami|vgpu'
```

GPU node allocatable 확인:

```bash
kubectl get nodes etri-ser0001-cg0msb etri-ser0002-cgnmsb \
  -o jsonpath='{range .items[*]}{.metadata.name}{" allocatable="}{.status.allocatable}{"\n"}{end}'
```

GPU 관측 확인:

```bash
curl -fsS http://aggregator.192.168.0.56.sslip.io/state/dashboard \
  | python3 -m json.tool \
  | grep -E 'hostname|gpu_utilization|gpu_memory_usage_ratio|gpu_temperature_celsius|gpu_power_watts'
```

## 문서/연구 해석 주의

과거 archive의 stage-level placement / runtime replanning 문서를 볼 때 HAMi는 새로 추가된 GPU runtime substrate로만 해석한다.
HAMi 설치 자체가 runtime replanning 기능 완성을 의미하지 않는다.
현재 활성 PoC 설명에서는 여전히 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화를 우선한다.
