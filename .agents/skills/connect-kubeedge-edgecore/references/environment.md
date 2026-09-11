# 현재 PoC 환경과 권위 자료

## 자료 우선순위

변경될 수 있는 값은 다음 순서로 판단한다.

1. live Kubernetes/KubeEdge 상태
2. 현재 checkout의 manifest와 실행 스크립트
3. 현재 운영 문서
4. 문서의 과거 예시값

외부 원본 `dsa04156/kubeedge-setup-scripts`에는 `v1.22.0` 기본값이 남아 있지만,
2026-08-14 live cluster의 CloudCore Helm chart와 기존 edge node는 `v1.23.0`이었다.
현재 checkout은 setup script에 버전을 명시하도록 보정했으며 이후 작업에서도 live 값을
반드시 다시 조회한다.

## 2026-09-09 VPN 운영 기준

서버1 `10.77.0.1`, 서버2 `.5`, Nano `.3`, Pi2 `.4`, Pi3 `.6`, AGX `.8`로 Node/Flannel을
전환했다. Tinker는 `192.168.0.7`이며 hub LAN 반환 경로를 유지한다. 아래 8월 스냅샷의 LAN
CloudCore 주소를 현재 VPN 노드의 기본값으로 복사하지 않는다. AGX는 wireguard-go다.
현재 재배포 진입점은 `kubeedge-tools/kustomization.yaml`과 `redeploy_network_helm.py`다.
[현재 재배포 설명](../../../../kubeedge-tools/README.md)을 우선한다.

## 2026-08-14 실측 스냅샷

이 값은 발견용 기준일 뿐 고정 설정이 아니다.

| 항목 | 실측값 |
|---|---|
| kubectl context | `kubernetes-admin@kubernetes` |
| CloudCore host node | `etri-ser0001-cg0msb` |
| CloudCore host address | `192.168.0.56` |
| CloudCore install | Helm `cloudcore-1.23.0`, app `1.23.0` |
| CloudCore network | `hostNetwork: true`, Deployment strategy `Recreate` |
| CloudHub | TCP `10000` |
| CloudHub QUIC | UDP `10001`, live config에서는 disabled였음 |
| CloudHub HTTPS | TCP `10002` |
| CloudStream | TCP `10003` |
| EdgeStream tunnel | TCP `10004` |
| edge node | `etri-dev0001-jetorn`, `etri-dev0002-raspi5`, `etri-dev0003-raspi5` |
| edge version | kubelet 문자열 기준 `kubeedge-v1.23.0` |
| edge runtime | containerd |
| Pod CIDR/CNI 자료 | `10.244.0.0/16`, repository edge/cloud Flannel manifest |
| cluster DNS Service IP | `10.96.0.10` |
| EdgeCore tailored cluster DNS example | `169.254.96.16` |

CloudCore Service는 ClusterIP지만 CloudCore Pod가 host network를 사용하므로 edge join에는 live host endpoint를 사용한다. `kubectl -n kubeedge get endpoints cloudcore -o wide`로 다시 확인한다.

## 현재 노드 라벨 관례

기존 edge node의 공통 라벨:

- `node-role.kubernetes.io/edge=`
- `node-role.kubernetes.io/agent=`
- `environment=edge`
- `edge.device/class=jetson` 또는 `edge.device/class=raspi`
- Tinker Edge R는 `edge.device/class=tinker-edge-r`

`edge.device/mapper=mqttvirtual`은 legacy test 경로다. 신규 노드에는 추가하지 않는다. `edgeai.etrilab/sensor-gateway=true` 같은 역할 라벨은 실제 역할과 workload 요구가 확인된 경우에만 추가한다.

현재 EdgeX Device Service manifest는 일부 노드를 `kubernetes.io/hostname`으로 정확히 지정한다. 새 node 등록만으로 기존 workload를 이동하거나 복제하지 않는다.

## 저장소 자료

| 경로 | 용도 |
|---|---|
| `kubeedge-tools/README.md` | cloud/edge 설치, join, patch, CNI, EdgeMesh, debug 개요 |
| `kubeedge-tools/setup-edge.sh` | edge host의 crictl/CNI/이미지/keadm 준비 |
| `kubeedge-tools/onboard-edge-lan.sh` | hostname/kernel/port/join/YAML patch를 수행하는 신규 LAN host 진입점 |
| `kubeedge-tools/patch-edge.sh` | hostname/CloudCore/containerd/metaServer 보정 후 EdgeCore 재시작 |
| `kubeedge-tools/patch_edgecore_config.py` | 생성된 EdgeCore YAML shape 검증과 원자적 patch |
| `kubeedge-tools/finalize-edge-lan.sh` | cloud 측 label, Flannel, EdgeMesh, monitoring, dashboard 검증 |
| `kubeedge-tools/config/edgemesh-values.yaml` | 현재 relay와 image digest의 non-secret Helm 기준 |
| `kubeedge-tools/setup-wireguard-cloud.sh` | 외부 edge용 cloud WireGuard endpoint 준비 |
| `kubeedge-tools/setup-wireguard-edge.sh` | 외부 edge peer 설정 |
| `kubeedge-tools/install-flannel-edge.sh` | edge용 Flannel DaemonSet 적용 |
| `references/upstream-script-coverage.md` | 외부 setup 저장소의 모든 자산별 반영·제외·안전 경계 |
| `edge-orch/scripts/check-edgecore-node.sh` | 조인 후 EdgeCore, CloudCore, DNS, kernel을 검증하는 현재 점검 스크립트 |
| `docs/ops/엣지-노드-조인-점검.md` | 점검 스크립트 사용법과 종료 코드 |
| `docs/ops/다른-서버-배포-실행-가이드.md` | 네트워크, 스토리지, monitoring과 전체 배포 경계 |
| `docs/대시보드-판단-정책.md` | node와 physical device의 서로 다른 상태 권위 |

`edge-orch/scripts/check-edgecore-node.sh`는 확인용 임시 debug/smoke Pod를 만들고 종료 시 삭제한다. 실행 전에 해당 cluster context와 node 이름을 다시 표시한다.

## 플랫폼 경계

- KubeEdge: edge node와 workload 배치/상태
- Prometheus/node-exporter: node resource snapshot
- EdgeX Core Metadata: physical Device/Profile/Device Service 상태
- EdgeX Core Data: Event/Reading과 freshness

Kubernetes Node `Ready`를 물리 센서 연결 성공으로 해석하지 않는다. KubeEdge Device/DeviceStatus와 MapperFramework를 EdgeX 병행 authority나 fallback으로 사용하지 않는다.

## 2026-08-18 Tinker Edge R 검증 결과

`etri-dev0004-tedger`는 ASUS Tinker Edge R, ARM64, Debian 10, kernel `4.4.194`이며
KubeEdge `v1.23.0` edge node로 `Ready` 상태다. 현재 edge node는 4대이고 EdgeMesh
DaemonSet은 전체 6개 node에서 6/6 Ready다.

이 노드의 검증된 런타임과 경로:

- containerd `1.7.32`, runc `1.4.2`
- EdgeCore websocket/HTTP/EdgeStream: `192.168.0.56:10000/10002/10004`
- edge Pod DNS: EdgeMesh local DNS `169.254.96.16`
- local HTTP registry: containerd `certs.d`에서 `192.168.0.56:5000`만 허용
- Flannel, EdgeMesh, local MQTT, node-exporter Ready
- Prometheus `192.168.0.7:9100` `up=1`, dashboard node health `healthy`

kernel의 IPv4 `filter`/`nat`, bridge forwarding, VXLAN과 `physdev`, `multiport`,
`comment`, `statistic` match는 실제 동작한다. 그러나 IPv4 `mangle`/`raw`와 IPv6
iptables는 없다. 현재 검증된 IPv4 PoC 경로는 동작하지만 전체 netfilter 지원으로
표현하지 않는다.
