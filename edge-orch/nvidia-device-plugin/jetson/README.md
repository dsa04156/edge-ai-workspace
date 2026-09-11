# AGX Orin GPU 공유 운영

대상은 `etri-dev0005-jetagx` 한 대다. NVIDIA Device Plugin v0.19.0의 Tegra
time-slicing으로 `nvidia.com/gpu.shared: 2`를 제공한다. 서버용 `../k8s/`와
독립된 배포이며 Nano·서버·EdgeX 수집 경로는 변경하지 않는다.

기존 Orin Nano의 별도 설치·검증은 [Nano 운영 안내](../nano/README.md)를 따른다.

GPU 한 개를 여러 서비스가 번갈아 쓰도록 **동시 할당 슬롯 두 개**를 만든다.
GPU 두 장이나 서비스마다 연산량·메모리가 50%씩 보장되는 구성이 아니다.
MIG·HAMi·MPS는 사용하지 않으며, GPU 메모리·장애·지연 격리는 보장하지 않는다.

## 확인한 환경

- NVIDIA Jetson AGX Orin Developer Kit, RAM 약 64GB
- JetPack `7.2.1-b49`, L4T `39.2.1-20260806224157`, kernel `6.8.12-1021-tegra`
- KubeEdge `v1.23.0`, containerd `2.3.4`, NVIDIA Container Toolkit `1.19.1-1`
- NVIDIA plugin 이미지: v0.19.0의 arm64 manifest digest를 `daemonset.yaml`에 고정
- 2026-09-08 실제 검증: [실행 기록](검증-2026-09-08.md)

## 호스트 준비와 배포

운영 책임자는 테스트베드 운영자다. 현재 live Argo CD Application이 없어 이 독립
디렉터리를 `kubectl apply -k`로 적용했다. Git checkout의 파일과 live 설정을 함께
보관하며, 자동 GitOps 동기화 상태로 설명하지 않는다. EdgeX 운영 root에 넣지 않는다.

AGX 호스트에서 GPU와 Toolkit이 설치돼 있고 `nvidia-smi -L`이 성공해야 한다.
적용 전 `/etc/containerd/config.toml`과 기존 `/etc/containerd/conf.d/`를 백업한다.
그 다음 아래 공식 Toolkit 명령을 실행한다. containerd 재시작은 대상 노드에만 한다.

```bash
sudo nvidia-ctk runtime configure --runtime=containerd --set-as-default
sudo systemctl restart containerd
sudo systemctl is-active containerd edgecore
```

KubeEdge에서 API의 `RuntimeClass`가 존재해도 EdgeCore가 이를 찾지 못하는 오류를
확인해, 이 노드의 containerd 기본 runtime을 `nvidia`로 설정했다. Pod에
`runtimeClassName`을 추가하지 않는다. CUDA 할당은 플러그인이 전달하는 장치 인덱스와
NVIDIA runtime이 처리한다. 일반 Python 이미지의 GPU 미요청 Pod에는 GPU가 주입되지
않는지도 시험한다. 이미지 자체의 `NVIDIA_VISIBLE_DEVICES=all`이나 수동 장치 주입은
슬롯 할당을 우회할 수 있으므로 GPU 서비스는 아래 자원 요청 계약을 사용한다.

작업 저장소 루트에서:

```bash
rtk proxy kubectl apply -k edge-orch/nvidia-device-plugin/jetson
rtk proxy kubectl rollout status daemonset/nvidia-jetson-device-plugin -n kube-system --timeout=60s
rtk proxy kubectl get node etri-dev0005-jetagx -o jsonpath='{.status.allocatable}'
```

`deviceDiscoveryStrategy: tegra`는 Orin을 NVML dGPU로 오인하는 경로를 피한다.
Tegra 플러그인은 정적 장치 등록이며 health check가 없으므로 등록·Running만으로
GPU 동작을 판정하지 않는다. 실제 CUDA probe와 서비스 readiness가 별도로 필요하다.

## 서비스별 Pod 계약

각 서비스는 독립 Deployment/Pod로 유지하고 **컨테이너별 공유 슬롯 하나**를 요청한다.
CUDA·JetPack·arm64와 호환되는 서비스 이미지를 사용한다.

```yaml
spec:
  nodeSelector:
    kubernetes.io/hostname: etri-dev0005-jetagx
  containers:
    - name: inference
      image: <검증된-arm64-CUDA-서비스-이미지-digest>
      env:
        - name: NVIDIA_DRIVER_CAPABILITIES
          value: compute,utility
      resources:
        limits:
          nvidia.com/gpu.shared: 1
```

CPU·RAM requests/limits와 모델 batch·동시 요청 수는 서비스 실측값으로 정한다.
Pod의 `memory` limit을 서비스별 GPU 메모리 분할로 해석하지 않는다.
`nvidia.com/gpu` 대신 `.shared`를 사용해 서버의 독점 GPU와 구분한다.
`failRequestsGreaterThanOne: true`이므로 컨테이너 하나가 공유 슬롯 두 개를 요청하는
방식은 사용하지 않는다. 슬롯 수 증가는 메모리 증가가 아니며 부하 재검증이 필요하다.

## 소규모 CUDA 공유 시험

운영 모델이나 포화 부하가 아닌 독립 CUDA kernel 시험이다. `smoke/probe.py`는
CUDA Driver API로 PTX를 실행하고 256개 정수 각각에 1을 더한 결과를 매회 검증한다.
한 Pod당 1KiB device allocation, 약 0.2초 간격으로 60초간 수행한다.
context와 driver 자체가 사용하는 추가 메모리는 이 1KiB에 포함되지 않는다.

```bash
rtk proxy kubectl apply -k edge-orch/nvidia-device-plugin/jetson/smoke
rtk proxy kubectl logs -n jetson-gpu-smoke cuda-share-a
rtk proxy kubectl logs -n jetson-gpu-smoke cuda-share-b
rtk proxy kubectl get pods -n jetson-gpu-smoke -o wide
rtk proxy kubectl delete -k edge-orch/nvidia-device-plugin/jetson/smoke
```

성공 기준은 두 Pod의 같은 GPU UUID, 겹치는 CUDA 계산 시간, 최종 `passed`, exit 0이다.
세 번째 요청의 Pending→슬롯 반환 후 실행, GPU 미요청 컨테이너의 미주입도 최초
검증 기록에 포함한다. 실제 AI 서비스 두 개의 처리량·p95·메모리·온도 검증은 별도다.

## 복구

GPU 소비 Pod를 먼저 정상 종료한 뒤 이 경로의 플러그인과 ConfigMap을 삭제한다.

```bash
rtk proxy kubectl delete -k edge-orch/nvidia-device-plugin/jetson
```

2026-09-08 적용 전 AGX 호스트 백업은
`/var/backups/jetson-timeslicing-20260908/containerd-config.toml`이다.
이번 적용 전에는 `conf.d/99-nvidia.toml`이 없었다. 호스트의 config.toml을 백업으로
복원하고 이번에 추가한 `conf.d/99-nvidia.toml`만 제거한 뒤 containerd를 재시작한다.
이후 추가 변경이 있으면 전체 백업 덮어쓰기 전에 차이를 확인한다.
새 GPU 소비 Pod가 생긴 상태에서 runtime이나 플러그인만 먼저 제거하지 않는다.

## 공식 근거

- [NVIDIA Device Plugin 공유 설정](https://github.com/NVIDIA/k8s-device-plugin/tree/v0.19.0#shared-access-to-gpus)
- [NVIDIA Container Toolkit containerd 설정](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- [AGX Orin time-slicing 사용자 보고](https://forums.developer.nvidia.com/t/does-jetson-orin-k8s-device-plugin-mps-work/344019/7)
