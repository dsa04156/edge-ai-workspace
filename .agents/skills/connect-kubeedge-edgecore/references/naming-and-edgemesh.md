# Hostname과 EdgeMesh 규칙

## Hostname

신규 edge node 이름은 조인 전에 아래 형식으로 확정한다.

| hardware | 형식 | 예시 |
|---|---|---|
| Jetson | `etri-devNNNN-jetorn` | `etri-dev0004-jetorn` |
| Raspberry Pi 5 | `etri-devNNNN-raspi5` | `etri-dev0004-raspi5` |
| ASUS Tinker Edge R | `etri-devNNNN-tedger` | `etri-dev0004-tedger` |

`NNNN`은 live cluster에서 비어 있는 4자리 sequence다. 다음 번호를 고를 때 모든 Node 이름을 조회하고, 삭제된 node의 재사용 여부도 운영자와 확인한다. 현재 저장소의 `jetorn` suffix는 기존 identity 호환을 위해 그대로 사용한다.

다른 hardware suffix를 즉석에서 만들지 않는다. 새 장비 class면 naming policy와 dashboard node classification을 먼저 갱신한다. Tinker Edge R는 `edge.device/class=tinker-edge-r`로 표시한다.

Kubernetes Node rename은 지원 흐름으로 취급하지 않는다. 잘못된 hostname으로 이미 조인했다면 기존 EdgeCore/Node/workload/PVC 영향을 진단한 뒤 승인된 rejoin 절차를 사용한다.

## LAN 주소

현재 CloudCore host endpoint는 실측상 `192.168.0.56`이지만 실행 전에 endpoint와 host node를 다시 조회한다. LAN onboarding은 private IPv4만 허용하고 다음 포트를 edge host에서 직접 확인한다.

- TCP `10000`: EdgeHub websocket/join
- TCP `10002`: CloudHub HTTPS
- TCP `10004`: EdgeStream tunnel

ClusterIP를 `--cloudcore-ipport`에 넣지 않는다.

## EdgeMesh

현재 EdgeMesh는 Helm release `edgemesh`, namespace `kubeedge`의 단일 DaemonSet이다. 2026-08-18 실측에서는 cloud 2대와 edge 4대, 총 6대에 모두 Ready였다.

현재 기준:

- relay node: `etri-ser0001-cg0msb`
- relay advertise address: `192.168.0.56`
- image: `kubeedge/edgemesh-agent@sha256:460c6061b6088d507bb547d362a8d803b75c7eeddd23758a4b218a5da9138364`
- non-secret values: `kubeedge-tools/config/edgemesh-values.yaml`

신규 node마다 release를 다시 설치하거나 relay/PSK를 바꾸지 않는다. edge/agent role이 등록되면 기존 DaemonSet이 자동 배치되는지 확인한다. PSK는 values 파일, Git, 대화 또는 로그에 저장하지 않는다.

완료 기준:

1. `kube-flannel-edge-ds` Pod가 신규 node에서 Ready
2. `edgemesh-agent` Pod가 같은 node에서 Ready
3. EdgeMesh 로그에 지속적인 peer mismatch/iptables 실패가 없음
4. host에 `br_netfilter`, `xt_physdev`가 load됨
5. `bridge-nf-call-iptables=1`, `ip_forward=1`
6. edge Pod에서 cluster DNS와 중앙 Service FQDN 접근 성공

EdgeMesh local DNS는 `169.254.96.16:53`을 사용한다. EdgeCore
`tailoredKubeletConfig.clusterDNS`가 빠지면 Pod가 host `/etc/resolv.conf`를 상속해
Node가 Ready여도 service DNS가 실패할 수 있다. CloudStream이 활성인 현재 cluster에서는
EdgeCore `edgeStream.enable: true`도 요구해 `kubectl logs/exec`를 검증한다.

relay Peer ID 오류가 있을 때만 live ConfigMap과 실제 relay identity를 비교한다. 신규 node 추가를 이유로 전체 EdgeMesh DaemonSet을 임의 재시작하지 않는다.
