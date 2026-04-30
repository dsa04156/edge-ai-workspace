# 노드 조인 체크 스크립트

새 노드를 클러스터에 조인한 뒤, 우리가 실제로 겪었던 문제를 빠르게 확인하기 위한 프리플라이트 스크립트다.

위치:
- [scripts/check-worker-node-join.sh](/home/etri/jinuk/edge-orch/scripts/check-worker-node-join.sh)

## 무엇을 확인하나

- 노드 `Ready` 상태
- `kube-dns` 서비스와 엔드포인트 존재 여부
- 대상 노드의 `kube-proxy` 존재 및 최근 `iptables-restore` 오류 여부
- 대상 노드의 `edgemesh-agent` 존재 여부
- host에서 `10.96.0.10:53` 접근 가능 여부
- pod 내부 DNS 해석 가능 여부
- `br_netfilter`, `xt_physdev` 모듈
- `net.bridge.bridge-nf-call-iptables`, `net.ipv4.ip_forward`
- NVIDIA 서버 노드라면:
  - `/dev/nvidia*`
  - `nvidia-smi`
  - `nvidia.com/gpu` allocatable

## 실행 방법

control-plane에서 실행:

```bash
bash scripts/check-worker-node-join.sh etri-ser0002-cgnmsb
```

예시:

```bash
bash scripts/check-worker-node-join.sh etri-ser0001-cg0msb
bash scripts/check-worker-node-join.sh etri-ser0002-cgnmsb
```

GPU까지 확인하려면:

```bash
bash scripts/check-worker-node-join.sh --check-gpu etri-ser0002-cgnmsb
```

## 종료 코드

- `0`: 실패 없음
- `2`: 하나 이상 실패

## 전제 조건

- `kubectl` 사용 가능
- `kubectl debug node/...` 사용 가능
- `busybox:latest` 이미지를 pull할 수 있어야 함

권장:
- 기본 실행은 공통 네트워크/서비스 체크만 수행한다.
- GPU smoke 검증은 `--check-gpu` 옵션을 줬을 때만 수행한다.
- GPU smoke 검증까지 정확히 보려면, 대상 노드 GPU를 이미 점유한 워크로드가 없는 시점에 실행하는 것이 좋다.

## 참고

이 스크립트는 우리가 실제로 겪었던 다음 문제를 빠르게 찾기 위해 만들었다.

- CoreDNS 서비스 VIP 접근 불가
- EdgeMesh DNS 프록시 경로 이상
- `kube-proxy`의 `iptables-restore` 실패
- 새 노드 커널 모듈/브리지 설정 누락
- GPU 노드인데 Kubernetes에 `nvidia.com/gpu`가 노출되지 않는 상태
