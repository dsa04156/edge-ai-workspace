# DGX Spark GPU 등록

`etri-ser0003-cg0ms0`(ARM64, NVIDIA GB10)에 NVIDIA device plugin v0.19.0을 독립 배포한다. 기존 amd64 서버 플러그인과 Jetson 플러그인은 재사용하거나 변경하지 않는다. 현재 수동 apply 경로이며 Argo CD 자동 동기화가 아니다.

## 호스트 준비

기존 NVIDIA 드라이버 580.173.02, Container Toolkit 1.20.0, containerd.io 2.2.1을 사용한다.

```bash
sudo nvidia-ctk runtime configure --runtime=containerd
sudo systemctl restart containerd
```

`/etc/containerd/conf.d/99-nvidia.toml`에 nvidia handler가 추가된다. 기본 runc와 VPN registry 설정은 유지한다. 원본 containerd 설정 백업은 `/var/backups/dgx-gpu-20260909/containerd-config.toml`. RuntimeClass `nvidia-spark`는 정확한 DGX hostname으로 스케줄링을 제한한다.

## 재배포와 사용

```bash
kubectl --context=kubernetes-admin@kubernetes apply -k edge-orch/nvidia-device-plugin/spark
```

GPU Pod의 spec에 아래 설정이 필요하다. 이미지도 ARM64·GB10 호환이어야 한다.

```yaml
runtimeClassName: nvidia-spark
containers:
  - name: application
    image: <ARM64 GPU application image>
    resources:
      limits:
        nvidia.com/gpu: 1
```

한 개 GPU를 요청하는 일반 GPU 자원으로 등록했다. time slicing, MIG 또는 메모리 분할은 설정하지 않았다. 다른 시스템의 GPU 전체 프로세스를 제한하거나 메모리 격리를 보장한다는 의미는 아니다.

## 검증

```bash
kubectl --context=kubernetes-admin@kubernetes apply -k edge-orch/nvidia-device-plugin/spark/smoke
kubectl --context=kubernetes-admin@kubernetes logs dgx-cuda-smoke
kubectl --context=kubernetes-admin@kubernetes delete -k edge-orch/nvidia-device-plugin/spark/smoke
```

2026-09-09: plugin Ready, capacity/allocatable `nvidia.com/gpu=1`. GPU 요청 Pod가 DGX에 스케줄되고 CUDA Driver API로 PTX 커널을 JIT·실행했다. 256개 결과가 1~256과 일치하고 checksum 32896, exit 0. 결과는 `results/2026-09-09.json`. 임시 시험 Pod·ConfigMap은 검증 후 삭제했다.

GB10 NVML 메모리 조회에 `Not Supported` 경고가 있어 plugin에서 메모리 용량을 검증했다고 표현하지 않는다. 실제 모델 추론 부하와 재부팅 후 복구는 별도 검증이다.

근거: [NVIDIA plugin v0.19.0](https://github.com/NVIDIA/k8s-device-plugin/tree/v0.19.0), [Container Toolkit 설정](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html#configuring-containerd-for-kubernetes).
