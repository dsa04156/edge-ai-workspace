# 신규 EdgeCore 노드 연결 Runbook

아래 명령은 템플릿이다. 실행 전 실제 context, 경로, hostname, host address와 version으로 치환한다. 토큰 값은 출력이나 작업 기록에 남기지 않는다.

## 1. Cloud 측 read-only 확인

```bash
kubectl config current-context
helm list -n kubeedge
kubectl -n kubeedge get deploy cloudcore -o wide
kubectl -n kubeedge get svc cloudcore -o wide
kubectl -n kubeedge get endpoints cloudcore -o wide
kubectl get nodes -l node-role.kubernetes.io/edge -o wide
kubectl get nodes -l node-role.kubernetes.io/edge \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.kubeletVersion}{"\t"}{.status.nodeInfo.containerRuntimeVersion}{"\n"}{end}'
kubectl -n kube-system get ds -o wide
kubectl -n kubeedge get ds -o wide
```

CloudCore host node와 host address를 구한다.

```bash
CLOUDCORE_NODE="$(kubectl -n kubeedge get pod -l kubeedge=cloudcore -o jsonpath='{.items[0].spec.nodeName}')"
kubectl get node "${CLOUDCORE_NODE}" \
  -o jsonpath='{.metadata.name}{"\t"}{range .status.addresses[?(@.type=="InternalIP")]}{.address}{end}{"\n"}'
```

다음 조건을 만족하지 않으면 중단한다.

- CloudCore Deployment ready replica가 1 이상
- Service endpoint가 존재
- Helm app version과 기존 edge node의 `kubeedge-vX.Y.Z`가 일치
- 선택한 address가 target edge host에서 라우팅 가능

## 2. Edge host 사전 점검

target edge host에서 실행한다.

```bash
hostnamectl --static
uname -m
cat /etc/os-release
systemctl is-active containerd
containerd --version
test -S /run/containerd/containerd.sock
timedatectl show -p NTPSynchronized --value
swapon --show
df -h / /var/lib/containerd
lsmod | grep -E 'br_netfilter|xt_physdev' || true
sysctl net.bridge.bridge-nf-call-iptables net.ipv4.ip_forward
cat /proc/filesystems | grep overlay
cat /proc/net/ip_tables_names
sudo iptables -t filter -S >/dev/null
sudo iptables -t nat -S >/dev/null
for match in physdev multiport comment statistic; do
  sudo iptables -m "${match}" -h >/dev/null
done
systemctl status edgecore --no-pager -n 40 || true
test -f /etc/kubeedge/config/edgecore.yaml && echo EXISTING_EDGECORE_CONFIG || true
command -v keadm >/dev/null && keadm version || true
```

CloudCore 실제 host address를 사용해 연결을 확인한다.

```bash
nc -vz -w 3 "${CLOUDCORE_HOST}" 10000
nc -vz -w 3 "${CLOUDCORE_HOST}" 10002
nc -vz -w 3 "${CLOUDCORE_HOST}" 10004
```

`10000`은 join/EdgeHub 필수다. 현재 시스템의 HTTP/stream 진단까지 운영하려면 `10002`와 `10004`도 확인한다. `10001/udp`는 live CloudCore QUIC가 활성화된 경우에만 검사한다.

Cloud 측에서 hostname 중복을 검사한다.

```bash
kubectl get node "${EDGE_NODE_NAME}" --ignore-not-found
```

이미 존재하면 신규 join으로 진행하지 말고 기존 Node와 host EdgeCore 상태를 먼저 비교한다.

## 3. 외부망이면 WireGuard 선행

LAN 밖의 edge host는 다음 repository 스크립트를 검토해 사용한다.

- `kubeedge-tools/setup-wireguard-cloud.sh`
- `kubeedge-tools/setup-wireguard-edge.sh`

필수 조건:

- edge마다 고유한 `10.77.0.x/32` 할당
- private key를 대화, Git, 문서, 로그에 노출하지 않음
- cloud의 peer `AllowedIPs`와 edge address가 정확히 일치
- `wg show`에서 최신 handshake와 traffic 확인
- tunnel address를 통한 CloudCore TCP `10000`, `10002`, `10004` 확인
- CloudCore certificate/advertise address가 선택한 tunnel 경로와 호환되는지 확인

기존 `/etc/wireguard/wg0.conf`를 덮어쓰지 않는다. 신규 interface 스크립트는 기본 미리보기이며 `--apply`가 있어야 생성한다. 기존 peer는 `wireguard_peer.py`로 미리보기 후 선택 적용한다. 이 도구는 기존 경로를 요구하고 `wg syncconf` 실패 시 복원하므로 hub 전체 재시작을 기본 절차로 사용하지 않는다. 노드 주소 전환은 `docs/ops/WireGuard-노드-통신-전환.md`의 별도 절차를 따른다.

## 4. Edge 준비

repository의 `kubeedge-tools` 디렉터리를 target host에 동일한 내부 구조로 복사한다. `EDGE_NODE_NAME`은 `etri-devNNNN-jetorn`, `etri-devNNNN-raspi5`, 또는 `etri-devNNNN-tedger` 형식이며 cloud에서 미사용임을 먼저 확인한다.

구형 vendor kernel에서는 join 전에 disposable container를 실행한다. Tinker Edge R
kernel `4.4.194`에서 runc `1.5.1`이 재현 가능한 SIGSEGV를 내고 runc `1.4.2`가 동일
bundle을 정상 실행한 실측 precedent가 있다. 버전을 무조건 낮추지 말고 같은 증상을
직접 재현한 경우에만 checksummed upstream runc `1.4.2`를 호환 pin으로 사용한다.

외부 registry blob pull이 반복 reset되면 operator host에서 정확한 `linux/arm64` OCI
image를 digest로 확인해 archive로 받고, 양쪽 SHA-256이 같은지 확인한 뒤 target
containerd에 import한다. import 성공 후 archive를 삭제한다.

PoC registry `192.168.0.56:5000`은 HTTP다. 이 registry image를 실행할 node에는
containerd CRI `registry.config_path=/etc/containerd/certs.d`와 exact-host
`hosts.toml`을 설정한다. 다른 registry에 대한 TLS 검증을 끄지 않는다.

```bash
cd "${EDGE_TOOLS_DIR}"
sudo -E env \
  EDGE_NODE_NAME="${EDGE_NODE_NAME}" \
  EDGE_NODE_CLASS="${EDGE_NODE_CLASS}" \
  CLOUDCORE_HOST="${CLOUDCORE_HOST}" \
  KUBEEDGE_VERSION="${KUBEEDGE_VERSION}" \
  CONFIRM_UNIQUE_NODE="${EDGE_NODE_NAME}" \
  ./onboard-edge-lan.sh
```

스크립트는 hostname과 kernel/sysctl을 설정하고 CloudCore TCP 경로를 확인한 뒤 `setup-edge.sh`, hidden token prompt, `keadm join`, EdgeCore YAML patch를 순서대로 실행한다. 설치된 `keadm`이 cluster version과 호환되지 않으면 join 전에 중단한다.

## 5. 토큰 생성과 join

edge host가 준비된 뒤 cloud 측에서만 토큰을 생성한다.

```bash
keadm gettoken
```

토큰을 파일에 저장하거나 명령 예시에 붙이지 않는다. `onboard-edge-lan.sh`의 interactive hidden prompt에만 입력한다.

shell tracing이 켜져 있으면 먼저 끈다. join 결과를 기록할 때 token이 포함된 전체 command line을 복사하지 않는다.

## 6. EdgeCore 보정과 확인

```bash
cd "${EDGE_TOOLS_DIR}"
sudo ./patch-edge.sh
sudo systemctl is-active edgecore
sudo systemctl status edgecore --no-pager -n 80
sudo journalctl -u edgecore --since '10 minutes ago' --no-pager
sudo grep -nE 'hostnameOverride|remoteImageEndpoint|remoteRuntimeEndpoint|runtimeType|containerRuntimeEndpoint|imageServiceEndpoint|metaServer|httpServer|websocket|edgeStream|server:' \
  /etc/kubeedge/config/edgecore.yaml
```

확인 기준:

- `hostnameOverride`가 승인한 hostname과 일치
- containerd endpoint가 `unix:///run/containerd/containerd.sock`
- `metaServer.enable: true`
- websocket `10000`, HTTP `10002`, edgeStream `10004`가 선택한 동일 CloudCore host를 가리킴
- live CloudCore의 `cloudStream.enable: true`와 맞춰 `edgeStream.enable: true`
- EdgeMesh를 사용하는 edge Pod용 `clusterDNS`가 `169.254.96.16`
- certificate/x509, websocket reconnect, runtime socket 오류가 반복되지 않음

## 7. Cloud 측 등록과 라벨

명시한 context로 확인한다.

```bash
KUBE_CONTEXT="${KUBE_CONTEXT}" \
EDGE_NODE_NAME="${EDGE_NODE_NAME}" \
EDGE_NODE_CLASS="${EDGE_NODE_CLASS}" \
CLOUDCORE_HOST="${CLOUDCORE_HOST}" \
  kubeedge-tools/finalize-edge-lan.sh
```

스크립트는 Ready/role을 확인하고 `environment=edge`, hardware class만 적용한다. legacy `edge.device/mapper`는 제거하며 edge Flannel, 기존 EdgeMesh, node-exporter와 dashboard 관측을 기다린다.

## 8. 조인 검증

repository root에서 실행한다. 이 스크립트는 임시 debug/smoke Pod를 만들고 정리한다.

```bash
kubectl --context "${KUBE_CONTEXT}" get node "${EDGE_NODE_NAME}" -o wide
bash edge-orch/scripts/check-edgecore-node.sh "${EDGE_NODE_NAME}"
kubectl --context "${KUBE_CONTEXT}" get pods -A \
  --field-selector "spec.nodeName=${EDGE_NODE_NAME}" -o wide
kubectl --context "${KUBE_CONTEXT}" -n kubeedge logs deploy/cloudcore \
  --since=10m --tail=300
```

점검 스크립트가 CloudStream/EdgeStream을 통해 smoke Pod 로그를 회수하고 DNS 결과를
판정하므로 `FAIL=0`인지 확인한다. `kubectl logs`가 `10350 connection refused`를 내면
Node Ready만으로 통과 처리하지 않는다.

대시보드 backend가 default namespace의 `state-aggregator:8000` Service이면 API server proxy로 확인한다.

```bash
kubectl --context "${KUBE_CONTEXT}" get --raw \
  '/api/v1/namespaces/default/services/http:state-aggregator:8000/proxy/state/nodes'
```

응답의 `hostname`에서 exact node 이름을 확인하고 node type, metric timestamp/source를 검증한다. Kubernetes Ready는 `kubectl get node` 결과와 함께 대조한다. node-exporter 표본이 없으면 Node Ready만으로 완료 처리하지 않는다.

## 9. 완료 후 별도 작업

신규 노드에 Device Service나 AI workload를 배치하려면 별도 변경으로 수행한다.

- exact `kubernetes.io/hostname` selector 변경 필요성 검토
- root `edgex/k8s/kustomization.yaml`과 Argo CD 경로 유지
- EdgeX Device/Profile 등록과 첫 Core Data Event 별도 검증
- 물리 디바이스 freshness와 Kubernetes Node Ready를 별도 상태로 보고
