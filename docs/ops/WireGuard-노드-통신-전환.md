# WireGuard 노드 통신 전환

## 현재 상태와 측정 경계

2026-09-09 실장비 적용 기준이다. **승인된 6대의 Node InternalIP·Flannel을 VPN으로 전환했다.**
Tinker는 합의한 대로 LAN을 유지하고 hub를 통한 영속 반환 경로를 사용한다.

| 노드 | 현재 Node / Flannel 주소 | 방식 |
|---|---|---|
| 서버1 `etri-ser0001-cg0msb` | `10.77.0.1` | WireGuard hub·제어 서버 |
| 서버2 `etri-ser0002-cgnmsb` | `10.77.0.5` | WireGuard worker |
| Nano `etri-dev0001-jetorn` | `10.77.0.3` | WireGuard edge |
| Pi2 `etri-dev0002-raspi5` | `10.77.0.4` | WireGuard edge |
| Pi3 `etri-dev0003-raspi5` | `10.77.0.6` | WireGuard edge |
| AGX `etri-dev0005-jetagx` | `10.77.0.8` | **wireguard-go** 사용자 공간 구현 |
| Tinker `etri-dev0004-tedger` | `192.168.0.7` | LAN 유지, `10.77.0.0/24 via 192.168.0.56` |

- API 서버 및 CloudHub 인증서에 VPN SAN을 추가하고 기존 CA·키·LAN/10.254 SAN을 보존했다.
  VPN/LAN에서 실제 CA·호스트명 검증을 통과했다. API 광고·kubeadm 가입 endpoint·cluster-info·
  kube-proxy는 `10.77.0.1:6443`, 전환 edge의 CloudHub/EdgeStream은 VPN 주소를 사용한다.
- CloudCore Helm revision 3, EdgeMesh revision 9. EdgeMesh relay에 VPN 주소를 추가하고 기존
  LAN 광고·PSK·image를 보존했다. 두 release 모두 오래된 Helm 값이 현재 live 수정을 덮지 않도록
  live baseline revision을 먼저 만들었다. 에이전트 7대는 한 대씩 재시작했다.
- WireGuard MTU `1380`, Flannel/Pod MTU `1330`. 기존 일반 Pod 83개의 네트워크 namespace와
  veth MTU를 직접 조정했다. Flannel은 `OnDelete`로 전환해 한 노드씩 교체했다.
- 임시 혼합 LAN/VPN 통신 허용은 제거했다. spoke AllowedIPs는 VPN `/24`와 Tinker `/32`다.
  WireGuard 시작 후 경로 복원, kubelet/EdgeCore의 WireGuard 시작 순서, Tinker 반환 경로를 영속화했다.
  복원 명령은 실장비에서 실행·검증했지만 **실제 재부팅·WAN 단절 시험은 하지 않았다**.
- 레지스트리는 기존 `192.168.0.56:5000/...` 이미지 이름을 유지하고 VPN mirror를 첫 번째로 사용한다.
  기존 LAN mirror/server는 복구용 후순위로 남겼다. AGX에서 캐시에 없던 20,870,851바이트를
  CRI로 내려받고 `wg0`의 레지스트리 패킷 30개와 image digest를 확인했다.
- 7대 Ready, 노드 간 통신, 노드별 DNS/ClusterIP, 1,330바이트 DF Pod 패킷, 로그/exec,
  센서 12개 최신 Event와 대시보드 freshness, Prometheus 7개 node target을 확인했다.
- 전환 중 AGX GPU 재등록으로 이전 실험 Pod가 admission 실패했으며 ReplicaSet의 대체 Pod가
  정상 실행됐다. 모델은 COLD 상태이며 추가 추론이나 워크로드 분산을 실행하지 않았다.
  벤치마크 클라이언트는 삭제된 EmptyDir 마운트 때문에 준비 검사에 실패해 동일 Deployment로
  정확한 Pod 하나를 재생성했다. 당시 마운트는 비어 있었으며 이전 임시 결과 보존은 확인할 수 없다.
- Tinker kernel `4.4.194`는 `CONFIG_TUN` 비활성 상태다. LAN 마지막 구간은 암호화되지 않는다.
  AGX는 커널 WireGuard 지원이 없어 wireguard-go를 사용하며 WAN 성능은 별도 검증 대상이다.
- 기존 노드 SSH 접근은 확보했다. **외부 공인 endpoint·UDP 포워딩·신규 원격 장비는 아직 미입력**이다.
  외부 worker/edge 가입은 실행하지 않았다. 새 가입 token 발급 시 cluster-info JWS 갱신을 확인한다.

쉽게 말하면, 여섯 장비의 노드·서비스 통신은 이제 VPN 주소를 사용한다. Tinker만 기존 LAN 길을
남겨 hub를 통해 연결했다. 기존 센서가 계속 들어오는 것까지 확인했지만 외부 장소에서 가입하는
시험과 장비 재부팅 시험은 아직 하지 않았다.

실측 기록: [전환 결과](../../kubeedge-tools/results/wireguard-20260909-completed/verification.json),
[노드 주소](../../kubeedge-tools/results/wireguard-20260909-completed/nodes.json),
[Pod 통신](../../kubeedge-tools/results/wireguard-20260909-completed/pod-network-matrix.json),
[모니터링](../../kubeedge-tools/results/wireguard-20260909-completed/prometheus-targets.json).
이전 `wireguard-20260909/`는 적용 전 준비 기록으로 보존한다.

## 도구와 입력

주소 목록은 [`wireguard-network.json`](../../kubeedge-tools/config/wireguard-network.json)을 사용한다.
기존 peer `10.77.0.47`은 소유권 확인 전까지 예약 주소로 보존한다. 비밀번호·개인 키·token은
이 파일이나 검토 결과에 넣지 않는다. 외부 신규 노드는 고유 이름, `worker` 또는 `edge`,
고유 VPN IP를 등록하며 `lan_ip`는 필요 없으면 null로 둔다. `migration_order`에도 추가한다.
현장 네트워크가 VPN·Pod·Service 대역이나 Tinker `/32` 경로와 충돌하면 가입을 중단한다.

운영자와 대상 Linux host에는 Python 3.10 이상을 사용한다. `host_network.py`의 의존성은
[`requirements-network.txt`](../../kubeedge-tools/requirements-network.txt)에 있다.
CloudHub 인증서 도구는 추가로 `cryptography>=41`이 필요하다(적용 host의 41.0.7 사용).
기존 OS의 Python을 교체하지 말고 별도 환경을 사용할 수 있다. 복구 타이머가 그 Python의
절대 경로를 사용하므로 검증·복구 완료 전 환경을 삭제하면 안 된다.

```bash
rtk proxy python3 kubeedge-tools/networkctl.py plan --live
rtk proxy python3 kubeedge-tools/networkctl.py render --live --output /tmp/wireguard-review
```

`render`는 live Flannel backend와 Helm의 관련 주소값을 읽어 **검토용 파일만 생성**한다.
기존 출력 디렉터리를 덮어쓰지 않는다. `plan.json`의 `applied:false`는 해당 render 명령이 변경을 실행하지 않았다는 뜻이며, 이미 전환한 live 상태를 부정하지 않는다.
`observed.json`에는 주소·노드 상태만 기록한다. Secrets와 전체 Helm values는 내보내지 않는다.

| 도구 | 기본 동작 | 실제 변경 |
|---|---|---|
| `networkctl.py` | 계획·관측·검토 파일 생성 | 클러스터/host 변경 없음 |
| `setup-wireguard-{cloud,edge}.sh` | 미리보기 | `--apply`, 신규 interface만 생성 |
| `wireguard_peer.py` | 기존 peer 변경 미리보기 | `--apply`, 기존 키·타 peer 보존, sync 실패 시 복구 |
| `host_network.py preview` | 변경할 파일명만 출력 | secret 포함 diff 출력 없음 |
| `host_network.py migrate --apply` | 대상 worker/edge host 변경 | 백업·5분 복구 타이머·서비스 재시작 |
| `host_network.py commit` | 명시적 검증 완료 확정 | 타이머 중단, 상태 committed |
| `host_network.py rollback` | 이전 host 설정 복원 | MTU·관리 파일·서비스 복구 |
| `prepare_vpn_routes.py` | 혼합 통신 경로 검토 | `--apply` 준비, 전환 후 `--finalize --apply` 정리 |
| `prepare_pod_mtu.py` | 기존 Pod namespace 검사 | `--apply`, hostNetwork 제외·정확한 veth MTU 변경 |
| `prepare_cloud_vpn.py` | CloudHub SAN 검토 | `--apply`, 기존 CA/key 및 live Helm 설정 보존 |
| `prepare_edgemesh_vpn.py` | relay 변경 검토 | `--apply --agent-chart-archive FILE`, PSK 보존 |
| `migrate_control_plane_vpn.py` | `preview` | `apply`, 10분 host 복구 타이머·별도 commit |
| `onboard-vpn-node.sh` | 역할별 가입 미리보기 | `--apply`, VPN/커널 점검 후 가입 |

## 전환 전 준비

1. context `kubernetes-admin@kubernetes`, 노드명, 기존 7대 Ready와 EdgeX 최신 Event 기준선을 확인한다.
2. 서버 1을 hub로 사용한다. 공인 IP/도메인의 **UDP 51820 → 192.168.0.56:51820** 포워딩을
   준비한다. 이 단계는 외부 가입용이며 기존 내부 노드 전환의 선행 조건은 아니다. 외부에서 실제 handshake가 생기는지 확인한다. 내부에서 자기 공인 주소로 접속한
   결과만으로 외부 접속 여부를 단정하지 않는다.
3. 서버 2와 AGX를 포함해 전환 대상의 VPN 연결을 먼저 준비한다. 기존 config와 키를 보존한다.
   신규 interface만 `setup-wireguard-*.sh --apply`로 생성한다. 기존 interface에 강제 덮어쓰기를 하지 않는다.
4. hub peer에는 해당 노드의 VPN `/32`, spoke에는 `10.77.0.0/24`와 Tinker
   `192.168.0.7/32`를 사용한다. 기본 인터넷 경로는 바꾸지 않는다.
5. `routing.json`대로 **명시적 경로와 반환 경로를 먼저** 준비한다. Tinker의
   `10.77.0.0/24` 경로는 `192.168.0.56`을 통하고, spoke의 Tinker `/32` 경로는 `wg0`를 통한다.
   hub에서 VPN peer 사이 및 VPN↔Tinker의 필요한 전달을 허용한다. 기존 방화벽 규칙을
   flush하거나 일반 LAN 전체를 VPN에 광고하지 않는다. Tinker LAN 구간은 암호화 구간이 아니다.
6. 현재 라우팅·규칙을 root 전용 백업에 보존한 뒤 배포 환경의 영속 네트워크 설정에도 반영한다.
   `prepare_vpn_routes.py --apply`는 혼합 전환 구간의 정확한 기존 LAN `/32`만 임시 허용하고
   `Table=off`로 외부 VPN endpoint의 재귀 라우팅을 막는다. 전환 후 모든 VPN 노드에서
   `--finalize --apply`로 임시 허용을 제거한다. 실패 복구는 파일/live WG 범위이며 이미 추가된
   route/sysctl/firewall은 해당 백업과 실제 상태를 비교해 운영자가 복구한다.
   임시 `ip route` 명령만 실행한 상태를 재부팅 가능한 구성으로 보고하지 않는다.
   `wireguard_peer.py`는 경로 생성 도구가 아니며 AllowedIPs를 덮는 기존 wg 경로가 없으면 중단한다.

예시: 이미 설정된 hub에 공개 키로 peer를 추가할 때 먼저 미리본다. 개인 키는 인자로 넘기지 않는다.

```bash
sudo python3 kubeedge-tools/wireguard_peer.py --public-key "$NODE_PUBLIC_KEY" --allowed-ips 10.77.0.5/32
sudo python3 kubeedge-tools/wireguard_peer.py --public-key "$NODE_PUBLIC_KEY" --allowed-ips 10.77.0.5/32 --apply
```

이 도구는 live에만 존재하는 미저장 peer가 있으면 중단한다. 파일과 interface의 공개 키도 비교한다.
기존 config의 주소·MTU·PostUp/PostDown 변경은 peer sync 범위에 포함하지 않는다.

## 서버와 Flannel 준비

- API SAN 도구는 추가 주소를 인자로 받는다. `--san 10.77.0.1` 없이 과거 기본 주소를
  실수로 선택하지 않도록 실행 주소를 명시한다. 이번 API SAN 추가는 이미 적용·검증했다.
- `cloudcore.values.json`, `edgemesh.values.json`은 **부분 Helm values**다. 설치된 release와
  `--reuse-values`만으로는 live patch가 보존되지 않으므로 현재 resource를 먼저 baseline revision으로
  기록하고 live 보존 post-renderer를 사용한다. EdgeMesh dependency는 공식 archive의 agent 하위
  chart만 복원했다(SHA256 `49614b252d76a083030799c67ba44c26af528a84aebbb523c277d19e34b6f3a4`).
  주소 목록만 추가한다고 CloudHub의 기존 인증서가 자동 갱신된다고 가정하지 않는다.
  기존 CA를 유지해 VPN SAN을 포함한 CloudHub 인증서를 준비하고 실제 제공 인증서를 검증한다.
  CloudCore 단일 hostNetwork Deployment의 `Recreate` 운영 방식을 유지한다.
- API bootstrap 최종 전환에서는 kubeadm `controlPlaneEndpoint`, `kube-public/cluster-info`의
  server, kube-proxy kubeconfig와 control-plane manifest의 광고 주소를 함께 검토한다.
  새 endpoint는 `10.77.0.1:6443`이다. cluster-info를 바꾸면 bootstrap signer의 JWS 갱신까지
  확인한 후 신규 worker를 가입시킨다. 기존 CA·etcd 데이터·노드 객체를 재생성하지 않는다.
- control-plane 변경은 `host_network.py`로 수행하지 않는다. 이 도구는 해당 역할을 거부한다.
  인증서·static manifest·kubeconfig·ConfigMap 백업과 로컬 복구 경로를 가진 운영자가 마지막에 적용한다.

아래는 준비된 검토 파일을 적용하는 명령이다. **VPN/반환 경로 준비 전 실행하지 않는다.**
모든 명령은 context를 고정한다. 다른 파일까지 한꺼번에 apply하지 않는다.

```bash
kubectl --context=kubernetes-admin@kubernetes apply -f /tmp/wireguard-review/flannel-interfaces.json
kubectl --context=kubernetes-admin@kubernetes patch ds kube-flannel-cloud-ds -n kube-system --type=strategic --patch-file /tmp/wireguard-review/flannel-cloud.patch.json
kubectl --context=kubernetes-admin@kubernetes patch ds kube-flannel-edge-ds -n kube-system --type=strategic --patch-file /tmp/wireguard-review/flannel-edge.patch.json
kubectl --context=kubernetes-admin@kubernetes patch cm kube-flannel-cfg -n kube-system --type=merge --patch-file /tmp/wireguard-review/flannel-mtu.patch.json
```

`OnDelete`라서 이 단계가 기존 Flannel Pod를 일괄 재시작하지 않는다. 초기 interface map은
관측된 LAN/VPN 상태를 보존한다. 공통 VXLAN MTU는 `1380`, 결과 Pod MTU는 `1330`이다.
ConfigMap 수정만으로 이미 만들어진 Pod의 veth MTU가 갱신되는 것은 아니다. Tinker를 포함해
기존 Pod의 MTU는 `prepare_pod_mtu.py`로 namespace·PodCIDR·veth를 검증해 직접 반영할 수 있다.
현재 Tinker에는 일반 Pod가 없어 Flannel MTU만 반영했다. PVC·Serial/I2C 연결과
노드 고정 workload를 보존하며 무차별 drain이나 CNI state 삭제를 하지 않는다.

## 한 노드씩 적용과 복구

순서: Raspberry Pi 2 → AGX → Jetson 1 → Raspberry Pi 3 → 서버 2 → 서버 1.
작업 대상과 다음 대상 사이에 end-to-end 검증을 둔다.

1. 해당 node의 `.host.json`과 도구를 대상 host에 전달한다. `preview`에서 변경할 파일명을 확인한다.
2. TLS SAN/CA, VPN IP·handshake, containerd와 certs.d 설정을 확인한다.
3. 해당 node의 `.interface.patch.json`만 ConfigMap에 적용하고, 그 node의 정확한 Flannel Pod만
   재생성한다. mount된 interface map이 갱신된 것을 먼저 확인한다.
4. `host_network.py migrate --apply`를 실행한다. kubelet/EdgeCore·레지스트리·WG MTU 변경은
   root 전용 백업에 보관된다. 새 레지스트리 설정은 기존 image namespace를 유지한다.
5. 아래 검증 후 300초 안에 commit한다. 시간 내 검증하지 못하면 자동 host rollback을 허용하고 원인을 점검한다.

```bash
sudo python3 kubeedge-tools/host_network.py preview --spec /path/etri-dev0002-raspi5.host.json
sudo python3 kubeedge-tools/host_network.py migrate --spec /path/etri-dev0002-raspi5.host.json --apply
# 출력된 정확한 state.json 경로 사용. 검증 성공 후에만:
sudo python3 kubeedge-tools/host_network.py commit --state /var/backups/edgeai-network/TRANSACTION/state.json --verified-end-to-end
# 실패했거나 원복할 경우:
sudo python3 kubeedge-tools/host_network.py rollback --state /var/backups/edgeai-network/TRANSACTION/state.json
```

**자동 타이머의 복구 범위는 해당 host의 관리 파일·WG MTU·서비스다.** 운영자가 변경한
Flannel ConfigMap/Pod, 라우터, Helm release까지 원격으로 되돌리는 기능은 아니다.
실패 시 운영자도 `.interface.rollback.json`을 적용하고 해당 Flannel Pod를 다시 만든다.
DaemonSet 전체 원복 파일은 JSON merge patch(`--type=merge`)로 적용해야 추가 volume이 남지 않는다.
전체 공통 MTU를 원복하려면 이미 전환한 노드/Pod의 MTU도 같이 복구해야 하므로 먼저 다음 전환을 중단한다.

## 신규 원격 worker / edge 가입

1. 공인 endpoint, SSH 경로·OS·architecture와 역할을 확인하고 주소 목록에 등록한다.
2. VPN interface를 생성하고 hub peer·반환 경로·MTU를 먼저 검증한다.
3. 기존 node가 없는 것을 고정 context에서 확인한다. 기존 kubelet/EdgeCore 상태가 있으면
   가입 스크립트가 거부한다. reset을 자동 실행하지 않는다.
4. 가입 전에 운영자가 `kube-flannel-network-interfaces` ConfigMap에 **정확한 새 node 이름 → `wg0`** 항목을 추가한다.
   현재 Flannel은 이 map을 읽으므로 항목이 없으면 기동하지 않는다. edge는 기존 가입 도구가
   `node-role.kubernetes.io/agent`와 `node-role.kubernetes.io/edge` 라벨을 모두 부여하는지 확인한다.
5. `NODE_ROLE`, `NODE_NAME`, `NODE_VPN_IP`, `CLOUD_VPN_IP`를 설정하고
   `bash kubeedge-tools/onboard-vpn-node.sh --check`로 미리본다.
6. worker는 현재 `KUBERNETES_VERSION=v1.31.14`, 공개 `DISCOVERY_CA_HASH`,
   `CONFIRM_UNIQUE_NODE`를 입력한다. 설치된 kubeadm/kubelet이 다르면 중단한다.
   edge는 `EDGE_NODE_CLASS`, live와 맞는 `KUBEEDGE_VERSION`, `CONFIRM_UNIQUE_NODE`가 필요하다.
7. 준비 후 `--apply`한다. token은 숨김 입력으로 받으며 worker는 root 전용 임시
   JoinConfiguration을 사용한다. 로그나 Git에 저장하지 않는다. 이후 생성된 `.host.json`으로
   레지스트리·MTU 설정을 적용하고 검증·commit한다. join 제출만으로 완료라고 보고하지 않는다.

현재 자동화는 준비된 containerd/kubeadm/kubelet 또는 EdgeCore 설치 경로를 사용한다.
신규 OS의 임의 패키지 업그레이드, 커널 교체, reset을 포함하지 않는다.

## 합격 기준과 검증 근거

- 기존 7대 및 신규 대상의 Node Ready와 예상 InternalIP; 기존 hostname·PodCIDR 보존.
- 전환된 노드의 Flannel public IP가 VPN IP이며 Tinker는 LAN IP 유지.
- 노드별 DNS/ClusterIP와 **양방향** Pod 통신; 작은 패킷과 큰 전송 모두 통과.
- 새로 받는 이미지의 정확한 digest 확인. cache hit만으로 registry 경로 성공을 판단하지 않는다.
- worker의 kubelet 로그 경로, edge의 CloudStream/EdgeStream을 통한 `kubectl logs/exec`.
- Prometheus의 새 주소에 최신 표본 존재, 대시보드에서 기존 node identity로 연결.
- Arduino·Sense HAT → EdgeX Core Data 최신 Event → 대시보드 freshness 연결 유지.
- VPN 재연결과 재부팅 후 경로·MTU 복원은 별도 실장비 검증한다.
- 원격 worker와 edge는 각각 검증한다. 한 종류 성공으로 다른 종류 성공을 대신하지 않는다.

로컬 자동시험:

```bash
rtk proxy uv run --no-project --with pytest --with pyyaml --with tomli python -m pytest -q kubeedge-tools/tests
```

자동시험은 주소/peer 충돌, 미저장 peer 보호, key/PSK 보존, 멱등성, sync/restart 실패 복구,
기존 kubelet 인증·EdgeCore runtime/DNS 보존, 가입 CA pin과 SAN 보존을 검증한다.
실제 VPN 단절·장비 재부팅·원격 가입의 성공 근거로 확대 해석하지 않는다.

2026-09-09 최종 자동시험은 **36 tests passed**, 신규 Python 도구 Ruff 통과, shell syntax 통과,
cloud/edge Flannel patch의 server dry-run 통과다. [최종 검증 기록](../../kubeedge-tools/results/wireguard-20260909-completed/verification.json),
[검토 계획과 미입력 항목](../../kubeedge-tools/results/wireguard-20260909/plan.json)을 함께 확인한다.


## 주요 root 전용 복구 기록

- API 인증서: `/var/backups/kubernetes/apiserver-san-20260909T071704Z`
- CloudHub 인증서·Helm: `/var/backups/kubeedge/vpn-cloud-1788940976758857694`
- 제어 서버 host: `/var/backups/edgeai-network/control-plane-1788942351556205890/state.json` (committed)
- 가입 endpoint: `/var/backups/edgeai-network/bootstrap-endpoints-1788942551840956355`
- EdgeMesh: `/var/backups/kubeedge/edgemesh-vpn-1788942592169770244`
- 각 원격 host: `/var/backups/edgeai-network/` 아래 host transaction, routing, runtime, pod-mtu, registry-order 백업

이 경로의 파일에는 인증 정보가 포함될 수 있으므로 Git이나 공개 결과 폴더로 복사하지 않는다.
전체 롤백은 인증서/endpoint, Flannel, host 설정, 라우팅의 의존 순서를 함께 계획해야 한다.
완료된 단일 host transaction의 rollback 명령만으로 전체 클러스터가 복원되는 것은 아니다.

근거: [EdgeMesh 공식 Helm 구성](https://github.com/kubeedge/edgemesh/blob/main/build/helm/edgemesh/README.md),
[containerd registry host 우선순위와 certs.d](https://github.com/containerd/containerd/blob/main/docs/hosts.md).


## 전환 후 재배포 기준

2026-09-09 추가 정리로 Flannel 공통 설정은 `kubeedge-tools/yamls/kube-flannel-common.yml`,
노드별 인터페이스는 `config/flannel-interfaces.yaml`, 통합 진입점은
`kubeedge-tools/kustomization.yaml`에 저장했다. 기존 적용 전 `results/` bundle을 현재 기본값으로
사용하지 않는다. 설치 스크립트는 기본 서버 dry-run이며 `--apply`로 명시적으로 반영한다.

CloudCore/EdgeMesh는 공개 network values와 `redeploy_network_helm.py`를 사용한다.
완전한 matching chart와 live resource 보존을 요구하며 키·PSK를 Git에 기록하지 않는다.
Flannel 및 두 Helm release의 서버 dry-run과 자동시험 41개를 통과했다.
자세한 명령과 의존성은 [재배포 진입점](../../kubeedge-tools/README.md)을 따른다.


## 2026-09-09 외부 워커 추가: 모빌인트

- SSH: `etri@10.254.70.228`, 기존 hostname `etri-ser0004-cgnms0` 유지.
- Ubuntu 22.04.5 / amd64 / kernel 6.8.0-79-generic. Kubernetes kubeadm·kubelet·kubectl `v1.31.14`를 설치하고 apt hold. containerd `2.2.1`, SystemdCgroup=true.
- WireGuard `10.77.0.10/32`, hub endpoint `10.254.192.217:51820`, MTU 1380. 새 peer만 추가해 hub 재시작 없이 handshake 검증. AllowedIPs는 VPN /24와 Tinker /32. Flannel Pod MTU 1330, PodCIDR `10.244.5.0/24`.
- swap 비활성 영속화, kernel forwarding, kubelet의 wg-quick 시작 의존성을 설정했다. `/var/backups/edgeai-worker-*`에 기존 fstab을 보관했다.
- 등록 중 임시 NoSchedule taint를 사용한 뒤 제거. Node Ready, Flannel·kube-proxy·EdgeMesh·cloud-iptables-manager·node-exporter Ready.
- 임시 smoke Pod에서 DNS와 중앙 서비스 HTTP, logs/exec를 검증했다. 기존 서버·Nano·Pi2·Pi3에서 신규 Pod HTTP 200, 신규 Pod namespace에서 기존 6개 노드 Pod에 DF 1330 패킷 성공. Tinker LAN 반환 통신도 성공.
- Prometheus `10.77.0.10:9100` up, state-aggregator node_health healthy. 기존 센서 12개 fresh.
- Docker CDN reset으로 EdgeMesh/iptables-manager를 기존 서버에서 동일 이미지로 export/import했다. 전송 tar SHA256 양쪽 일치 확인 후 정리.
- containerd 기본 Transfer Service 경로에서 registry hosts 설정이 적용되지 않아 LAN HTTPS로 timeout됨을 확인했다. 이 노드는 `use_local_image_pull=true`로 설정한 뒤 VPN HTTP registry를 통한 실제 CRI pull에 성공했다. 정확한 `192.168.0.56:5000` image namespace만 `http://10.77.0.1:5000`으로 연결하며 전역 TLS 예외는 없다. [containerd 2.2 이미지 pull 설정](https://github.com/containerd/containerd/blob/release/2.2/docs/cri/config.md#image-pull-configuration-since-containerd-v21).
- DGX Spark `etri@10.254.70.183`은 SSH 인증 실패로 미등록·미변경. 별도 인증 정보 필요.
- 장비 추가는 워커 등록 검증이다. 모빌인트 NPU device plugin·추론 서비스는 설치/실증하지 않았으며 실제 재부팅은 미검증이다.


## 2026-09-09 외부 워커 추가: DGX Spark

- 추가 인증 정보로 접속 후 기존 hostname `etri-ser0003-cg0ms0` 유지. SSH `etri@10.254.70.183`. 앞 절의 인증 대기는 해소됐다.
- Ubuntu 24.04.3 / ARM64 / kernel 6.17.0-1032-nvidia, GB10 드라이버 580.173.02 확인. 기존 실행 Docker 컨테이너는 없었고 containerd.io 2.2.1의 CRI 비활성 설정을 백업 후 활성화했다. Docker와 NVIDIA 드라이버는 재설치하지 않았다.
- kubeadm·kubelet·kubectl v1.31.14 설치 및 hold, SystemdCgroup=true, use_local_image_pull=true, pause 3.10. swap 비활성·forwarding·kubelet WG 시작 의존성 영속화. 백업 `/var/backups/edgeai-worker-1788950361`.
- VPN 10.77.0.9/32, hub 10.254.192.217:51820, MTU1380. 새 peer만 추가했고 기존 WG 서비스는 재시작하지 않았다. Flannel PodCIDR 10.244.7.0/24, MTU1330. inventory/Flannel 인터페이스 map 반영.
- Node Ready, ARM64 smoke Pod 실행, DNS·서비스 HTTP·logs/exec 성공. 기존 서버2대·Nano·Pi2·Pi3·AGX에서 신규 Pod HTTP200, 신규 Pod namespace에서 기존6곳 DF1330, 모빌인트 VPN DF1380 및 Tinker ping 성공. Prometheus 10.77.0.9:9100 up, dashboard healthy, 기존 센서12 fresh.
- VPN registry CRI pull 성공. 이것은 이미지 전송 검증이며 모든 기존 이미지의 ARM64 실행 호환성을 의미하지 않는다.
- EdgeMesh의 외부 CDN 다운로드가 reset되어 AGX의 동일 digest ARM64 이미지를 export/import했다. 세 지점 tar SHA256 `cf6a7b0d48892627265672c9339d967c3dba72e70d6c736f377dbeb1e92b90b8` 일치를 검증했다.
- GPU device plugin·GPU 추론 workload는 이번 워커 등록 범위에 포함하지 않았다. 실제 재부팅 복구도 미검증이다.

최종 확인: 기존 7대와 신규 워커 2대, 총 9대 Ready. 신규 두 워커의 필수 DaemonSet·Prometheus·대시보드 정상. 네트워크 설정 테스트 41개 통과. 확인 근거: `kubeedge-tools/results/worker-onboarding-20260909.json`.
