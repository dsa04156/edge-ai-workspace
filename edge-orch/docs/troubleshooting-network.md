# 트러블슈팅: 노드 네트워크 및 EdgeMesh 복구

이 문서는 새 워커 노드 `etri-ser0002-cgnmsb`를 클러스터에 추가한 뒤 발생한 네트워크 연결 문제와 복구 과정을 기록한다.

## 1. 증상

- 새 노드에서 Kubernetes API 서버 `10.96.0.1:443`에 연결할 수 없었다.
- 클러스터 전체에서 DNS 장애가 발생했고 `1.1.1.1` 질의가 I/O timeout으로 실패했다.
- EdgeMesh 로그에 `peer id mismatch`와 `failed to install iptables rule (physdev match missing)`가 나타났다.
- 네트워크 구성이 실패해서 DNS가 죽고, DNS가 죽어서 네트워크 부트스트랩도 완료되지 않는 순환 문제가 생겼다.

## 2. 원인 분석

### A. CoreDNS 순환 의존성
새 노드의 CNI(Flannel)와 EdgeMesh 구성이 완료되기 전에 스케줄러가 CoreDNS Pod를 그 노드에 올렸다.
다른 Pod들, 예를 들어 `cloud-iptables-manager`는 API 서버를 찾기 위해 CoreDNS에 의존하므로, 노드는 자기 자신을 부트스트랩하지 못한 채 미구성 상태에 머물렀다.

### B. EdgeMesh Peer ID 불일치
`edgemesh-agent-cfg` ConfigMap 안의 bootstrap relay Peer ID(`...ijb`)가 오래된 값이었다.
실제 relay 서버 `etri-ser0001-cg0msb`는 다른 ID(`...GgD`)를 사용 중이었고, 그 결과 보안 프로토콜 협상이 실패했다.

### C. 호스트 커널 설정 부족
새 호스트에서 `br_netfilter`와 `xt_physdev` 커널 모듈이 활성화되지 않았다.
이 때문에 EdgeMesh가 서비스 인터셉트를 위한 `iptables` 규칙을 설치하지 못했다.

## 3. 해결 절차

### 1단계: 클러스터 DNS 복구
순환 의존성을 끊기 위해 CoreDNS를 안정적인 control-plane 노드에 고정했다.

```bash
kubectl patch deployment coredns -n kube-system -p '{"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "etri-ser0001-cg0msb"}}}}}'
```

### 2단계: EdgeMesh 설정 수정
`edgemesh-agent-cfg` ConfigMap의 relay 노드 정보와 Peer ID를 실제 서버 값에 맞게 수정한 뒤 agent를 재시작했다.

```bash
# edgemesh-agent-cfg의 relayNodes를 실제 서버 hostname/ID에 맞게 수정
kubectl rollout restart ds edgemesh-agent -n kubeedge
```

### 3단계: 호스트 커널 설정 적용
새 노드 `192.168.0.5`에 필요한 모듈과 bridge 관련 sysctl을 수동으로 적용했다.

```bash
sudo modprobe br_netfilter
sudo modprobe xt_physdev
sudo sysctl -w net.bridge.bridge-nf-call-iptables=1
sudo sysctl -w net.ipv4.ip_forward=1
```

## 4. 검증

- Peer 연결: EdgeMesh 로그에 `New stream between peer ... success`가 나타난다.
- DNS 해석: 새 노드에서 내부/외부 DNS 질의가 정상 동작한다.
- 서비스 라우팅: 필요한 `iptables` 규칙이 정상 설치되어 게이트웨이 경로로 트래픽이 흐른다.

## 5. 이후 노드 추가 시 예방 수칙

- 핵심 인프라 고정: DNS, Registry 같은 핵심 인프라는 안정적인 cloud 노드에 고정한다.
- 사전 점검: 노드 프로비저닝 단계에 `br_netfilter` 활성화를 포함한다.
- 설정 동기화: relay 서버가 재시작되거나 바뀐 뒤에는 EdgeMesh Peer ID를 반드시 재확인한다.
