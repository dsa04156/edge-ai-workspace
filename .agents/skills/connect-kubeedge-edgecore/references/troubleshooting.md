# EdgeCore 연결 문제 분류

## Node가 생성되지 않음

확인 순서:

1. target host에서 CloudCore TCP `10000` 접근
2. live CloudCore host endpoint를 사용했는지 확인
3. CloudCore와 EdgeCore version 일치
4. token을 join 직전에 발급했는지 확인
5. EdgeCore journal의 x509, token, websocket 오류
6. CloudCore 최근 로그의 certificate signing/registration 오류

```bash
sudo journalctl -u edgecore --since '15 minutes ago' --no-pager
kubectl -n kubeedge logs deploy/cloudcore --since=15m --tail=500
```

token 값 자체는 로그/보고서에 복사하지 않는다.

## Node가 NotReady

확인 순서:

1. `systemctl is-active edgecore`
2. `hostnameOverride`와 Kubernetes Node 이름
3. `/run/containerd/containerd.sock` 존재와 containerd active
4. generated EdgeCore config의 runtime endpoints
5. time synchronization과 certificate validity
6. host routing, firewall, WireGuard handshake

`kubeedge-tools/patch-edge.sh`를 다시 실행하기 전 diff 또는 backup으로 현재 config shape를 확인한다. 다른 버전의 YAML 필드를 무작정 추가하지 않는다.

## Pod가 Pending 또는 ContainerCreating

확인 순서:

1. Pod `nodeSelector`, affinity, taint/toleration
2. image architecture와 registry 접근
3. containerd image pull 로그/인증
4. edge용 CNI DaemonSet과 interface
5. EdgeCore meta server와 cluster DNS
6. PVC가 요구되면 해당 node의 StorageClass/provisioner 지원

```bash
kubectl describe pod -n "${NAMESPACE}" "${POD}"
kubectl get events -A --sort-by=.lastTimestamp | tail -n 100
sudo journalctl -u edgecore --since '15 minutes ago' --no-pager
```

Flannel과 Calico를 동시에 설치해 해결하려 하지 않는다.

### image pull 유형 분리

- `HTTP response to HTTPS client`: exact LAN registry의 containerd `certs.d/hosts.toml` 누락
- 외부 CDN blob `connection reset by peer`: platform digest와 양쪽 archive checksum을
  확인한 뒤 trusted operator host에서 전송/import
- init container 하나만 끝나고 다음 image에서 장시간 정지: kernel 실패로 단정하지 말고
  containerd의 active pull과 image inventory를 먼저 확인

## DNS 또는 ClusterIP Service 실패

repository check가 보는 두 경로를 구분한다.

- host에서 cluster DNS Service IP `10.96.0.10:53`
- EdgeCore/EdgeMesh가 제공하는 edge Pod DNS 경로와 `169.254.96.16` 예시

확인 항목:

- kube-dns/CoreDNS Service와 endpoint
- `edgemesh-agent`가 target node에 실행되는지
- `metaServer.enable: true`
- `tailoredKubeletConfig.clusterDNS: [169.254.96.16]`
- `br_netfilter`, `xt_physdev`, `bridge-nf-call-iptables=1`, `ip_forward=1`
- edge Pod에서 `kubernetes.default.svc.cluster.local` 해석

Node Ready가 true여도 이 경로가 실패하면 onboarding은 부분 성공이다.

## kubectl logs/exec 또는 metrics만 실패

CloudHub 연결과 CloudStream/EdgeStream을 분리해 본다.

- `10000`: EdgeHub websocket
- `10002`: CloudHub HTTPS
- `10003`: CloudStream
- `10004`: EdgeStream tunnel

EdgeCore `edgeStream.server`가 live CloudCore host의 `10004`를 가리키는지 확인한다. CloudCore가 Helm 설치라면 stream certificate와 feature가 현재 config에서 활성인지 먼저 조회하고, 과거 수동 certificate 절차를 바로 적용하지 않는다.

server 주소만 맞고 `edgeStream.enable: false`이면 Node/Pod는 Ready여도 API server의
`kubectl logs/exec` 프록시는 실패한다. live CloudCore의 `cloudStream.enable`을 확인한 뒤
EdgeCore를 활성화하고 실제 completed smoke Pod 로그를 조회한다.

현재 운영 CloudCore는 hostNetwork 단일 replica와 `Recreate` 전략을 사용한다. 문제 해결을 위해 임의 rolling restart나 두 replica로 확장하면 host port 충돌을 만들 수 있다.

## 대시보드에서만 누락

확인 순서:

1. `/state/nodes` raw 응답에 exact hostname이 있는지
2. Prometheus `up{job="node-exporter"}`에 새 node 표본이 있는지
3. node-exporter DaemonSet node affinity/toleration
4. InternalIP와 exporter instance를 aggregator가 동일 node로 매핑하는지
5. metric timestamp가 freshness window 이내인지

metric 누락을 0% 사용량으로 해석하지 않는다. Kubernetes Ready와 Prometheus 관측 누락을 각각 보고한다.

## 기존 host 재연결/재설치

다음은 파괴적 작업이다.

- `keadm reset`
- Kubernetes Node 삭제
- `kubeedge_k8s_full_reset.sh`
- CNI interface/state 제거
- iptables/nftables flush
- WireGuard config overwrite

사용자가 명시적으로 재설치를 요청한 경우에만 exact hostname/host를 다시 확인하고, 현재 EdgeCore config와 journal, node-bound workloads/PVC, WireGuard config를 먼저 보존한다. reset 범위를 최소화하고 성공 검증 전 기존 Node object나 workload binding을 성급히 제거하지 않는다.

## Tinker Edge R vendor kernel

`etri-dev0004-tedger`는 ASUS Tinker Edge R, Debian 10, vendor kernel `4.4.194`다.
2026-08-18 재검증에서 IPv4 `filter`/`nat`, bridge forwarding, VXLAN과 `physdev`,
`multiport`, `comment`, `statistic` match가 실제 동작했고 KubeEdge node, Flannel,
EdgeMesh, Pod DNS, `kubectl logs`, Prometheus와 dashboard 검증을 통과했다.

다음 제한은 남아 있다.

- `/proc/net/ip_tables_names`에는 `filter`, `nat`만 있고 IPv4 `mangle`, `raw`가 없음
- `ip6_tables`와 IPv6 filter/mangle/raw/nat가 없음
- EdgeCore 시작 시 `KUBE-IPTABLES-HINT` mangle/IPv6 초기화 warning이 발생
- `modules.builtin.bin`이 없어 built-in 기능도 `modprobe`만 보면 false negative가 됨

따라서 현재 IPv4 Flannel/EdgeMesh/DNS/일반 Pod 경로는 사용 가능하지만, mangle/raw 또는
IPv6 iptables에 의존하는 기능, dual-stack, 전체 netfilter compliance는 검증되지 않았다.
그 기능이 필요하면 vendor accelerator 호환성을 보존한 kernel rebuild 또는 새 OS/kernel
검증이 다음 안전 작업이다.

### old-kernel runtime precedent

containerd `1.7.32`와 runc `1.5.1` 조합에서 disposable bundle이 libpathrs/openat2
fallback 경로로 SIGSEGV를 재현했다. checksummed runc `1.4.2`로 동일 bundle과 CRI가
정상 실행됐다. 일반 node의 runc를 선제 downgrade하지 말고, 이 exact old-kernel crash를
재현했을 때만 scoped compatibility pin으로 사용한다.
