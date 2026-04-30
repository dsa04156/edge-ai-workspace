# EdgeCore 노드 조인 체크 스크립트

KubeEdge `edgecore` 노드 전용 프리플라이트 스크립트다.
새 Jetson/Raspberry Pi 같은 edge node를 붙인 뒤, cloud/worker용 체크와는 별도로 edgecore 동작 여부를 빠르게 확인한다.

위치:
- [scripts/check-edgecore-node.sh](/home/etri/jinuk/edge-orch/scripts/check-edgecore-node.sh)

## 무엇을 확인하나

- 노드 `Ready`
- edge/agent 라벨 존재 여부
- `cloudcore` 서비스와 엔드포인트
- 대상 노드의 `edgemesh-agent`
- host의 `edgecore` systemd 서비스 활성화 여부
- `/etc/kubeedge/config/edgecore.yaml` 존재 여부
- `edgecore.yaml` 안의 upstream server 설정
- host에서 `10.96.0.10:53` 접근 가능 여부
- host에서 `kubernetes.default.svc.cluster.local` 해석 가능 여부
- pod 내부 DNS 해석 가능 여부
- `br_netfilter`, `xt_physdev`
- `bridge-nf-call-iptables`, `ip_forward`

## 실행 방법

```bash
bash scripts/check-edgecore-node.sh etri-dev0001-jetorn
bash scripts/check-edgecore-node.sh etri-dev0002-raspi5
```

## 종료 코드

- `0`: 실패 없음
- `2`: 하나 이상 실패

## 참고

이 스크립트는 edge node 조인 시 다음 문제를 빨리 잡기 위해 추가했다.

- `edgecore` 서비스 미기동
- `edgecore.yaml` 누락 또는 upstream server 설정 누락
- `cloudcore` 경로 이상
- EdgeMesh DNS 프록시 이상
- 새 edge node의 DNS VIP 접근 실패
- 커널 모듈/브리지 설정 누락
