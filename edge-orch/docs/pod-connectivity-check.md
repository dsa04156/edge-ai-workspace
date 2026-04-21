# 파드 간 통신 체크 스크립트

조인 체크가 기본 인프라 상태를 본다면, 이 스크립트는 실제 same-node / cross-node 파드 간 통신을 확인한다.

위치:
- [scripts/check-pod-connectivity.sh](/home/etri/jinuk/edge-orch/scripts/check-pod-connectivity.sh)

## 무엇을 확인하나

- source 노드에 테스트 서버 pod 생성
- target 노드에 테스트 서버 pod 생성
- source 노드의 client pod에서 다음을 확인
  - same-node service 접근
  - same-node direct pod IP 접근
  - cross-node service 접근
  - cross-node direct pod IP 접근
  - `kubernetes.default.svc.cluster.local` DNS 해석

## 실행 방법

worker에서 control-plane 방향 예시:

```bash
bash scripts/check-pod-connectivity.sh etri-ser0002-cgnmsb etri-ser0001-cg0msb
```

edge에서 server 방향 예시:

```bash
bash scripts/check-pod-connectivity.sh etri-dev0001-jetorn etri-ser0001-cg0msb
bash scripts/check-pod-connectivity.sh etri-dev0002-raspi5 etri-ser0001-cg0msb
```

## 종료 코드

- `0`: 실패 없음
- `2`: 하나 이상 실패

## 참고

이 스크립트는 실제 앱 포트 대신 임시 HTTP pod를 띄워서 네트워크 레벨 연결성을 확인한다.
실제 서비스 검증까지 하려면 이후에 `workflow_executor`, `placement_engine`, `cloudcore` 등 실제 포트 기준 점검을 추가하면 된다.
