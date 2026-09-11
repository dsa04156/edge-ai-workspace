# Orin Nano GPU 공유 운영

기존 `etri-dev0001-jetorn` Orin Nano에도 NVIDIA 공식 Device Plugin v0.19.0을
설치한다. [AGX 설정](../jetson/README.md)을 재사용하는 독립 Kustomize overlay이며,
DaemonSet·ConfigMap 이름과 selector를 분리했다. AGX DaemonSet을 교체하지 않는다.

- GPU 자원: `nvidia.com/gpu.shared: 2`, 컨테이너당 `1` 요청
- 방식: Tegra discovery, envvar/index, time-slicing. HAMi·MIG·MPS 사용 없음
- 하드웨어: Orin Nano Super 개발 키트, RAM 약 8GB
- L4T `36.4.7-20250918154033`, NVIDIA Container Toolkit `1.16.2-1`
- `nvidia-jetpack` 메타 패키지가 없어 정확한 JetPack 세부 버전을 단정하지 않는다.
- containerd `2.2.1`, KubeEdge `1.23.0`

## 적용

Nano에는 NVIDIA runtime handler가 이미 있었으나 기본 runtime은 `runc`였다.
2026-09-08 승인 작업에서 `/etc/containerd/config.toml`의
`default_runtime_name` 한 항목만 `nvidia`로 바꾸고 containerd를 재시작했다.
기존 파일은 호스트의
`/var/backups/jetson-nano-timeslicing-20260908/containerd-config.toml`에 보관한다.
RuntimeClass는 AGX에서 확인한 KubeEdge 조회 문제 때문에 사용하지 않는다.

```bash
rtk proxy kubectl apply -k edge-orch/nvidia-device-plugin/nano
rtk proxy kubectl rollout status ds/nvidia-jetson-device-plugin-nano -n kube-system --timeout=60s
rtk proxy kubectl get node etri-dev0001-jetorn -o jsonpath='{.status.allocatable}'
```

현재 live Argo CD Application이 없어 별도 수동 적용한다. 이 경로를 자동
GitOps 동기화 또는 EdgeX 배포로 설명하지 않는다. 신규 GPU 서비스는 Nano hostname과
`resources.limits.nvidia.com/gpu.shared: 1`을 지정한다. 상세 Pod 계약은 AGX 안내를 따른다.

## 기존 GPU 시험 Pod의 경계

`llama-offload-eval/llama-worker-nano`의 기존 컨테이너는 privileged·호스트 라이브러리
mount로 GPU를 직접 사용하며 공유 슬롯을 요청하지 않는다. 이번에는 해당 시험
Deployment를 변경하거나 재시작하지 않는다. 따라서 슬롯 2개는 **전체 GPU 사용
프로세스 수를 2개로 강제 제한한다는 뜻이 아니다**. 기존 직접 접근 소비자의
이관은 해당 시험의 배포 계약과 검증을 별도로 갱신해야 한다.

RAM 8GB는 OS·CPU·GPU가 함께 사용한다. 모델 두 개가 실제로 들어가는지와 지연·
처리량은 서비스별 실측이 필요하다. 슬롯 2개가 메모리나 연산량의 50%씩을 보장하지 않는다.

## 검증과 정리

AGX에서 사용한 실제 CUDA kernel probe를 Nano의 독립 namespace에 배포한다.

```bash
rtk proxy kubectl apply -k edge-orch/nvidia-device-plugin/nano/smoke
rtk proxy kubectl logs -n jetson-nano-gpu-smoke cuda-share-a
rtk proxy kubectl logs -n jetson-nano-gpu-smoke cuda-share-b
rtk proxy kubectl get pods -n jetson-nano-gpu-smoke -o wide
rtk proxy kubectl delete -k edge-orch/nvidia-device-plugin/nano/smoke
```

성공 기준: 같은 CUDA GPU UUID, 겹치는 계산 구간, 두 Pod의 최종 `passed`와 exit 0.
첫 적용에서는 세 번째 Pod의 슬롯 대기·반환 후 실행, GPU 미요청 Pod 미주입,
기존 운영 Pod UID·containerID·restartCount 유지도 확인한다.

### 2026-09-08 실제 결과

- Nano plugin `nvidia-jetson-device-plugin-nano` 1/1 Ready, restart 0,
  `nvidia.com/gpu.shared: 2` 확인. AGX도 기존 2슬롯을 유지한다.
- 두 독립 Pod에서 CUDA UUID `fa3cafc699485d928c81fa5172db713e` 일치.
  각각 60초·298회 실제 kernel 결과 검증, checksum `32896`, exit 0.
  시작 시각이 달라 두 계산 구간의 겹침은 **39.873초**다.
- 세 번째 Pod는 `Insufficient nvidia.com/gpu.shared`로 Pending이었다가
  앞선 Pod의 슬롯 반환 후 25회 계산·검증, exit 0.
- GPU 미요청 Python Pod는 `driver_not_injected`, GPU 접근 없음, exit 0.
- 기존 Pod 12개는 UID·containerID·restartCount가 전부 동일하고 모두 Ready.
- 이 결과는 작은 CUDA 공유 기능 시험이며 실제 모델의 동시 성능·GPU 격리·
  호스트 재부팅 복구를 입증하지 않는다.

근거: [검증 요약](results/2026-09-08/verification.json),
[동시 실행·대기 관측](results/2026-09-08/concurrent-and-pending.json),
[기존 Pod 전후 비교](results/2026-09-08/existing-pods-after.json).
같은 결과 디렉터리에 A/B/C와 GPU 미요청 Pod의 CUDA JSONL 로그를 보관한다.
시험 namespace와 이번 진단 Pod 두 개는 삭제 후 잔여 객체가 없음을 확인했다.

복구 시 새 GPU 소비 Pod를 먼저 정상 종료하고 `kubectl delete -k`로 이 Nano
overlay만 삭제한다. 호스트 설정의 이후 변경을 비교한 뒤 백업에서 기본 runtime
설정을 복원하고 containerd를 재시작한다. AGX·서버 설정은 함께 삭제하지 않는다.
