# KubeEdge Tools

Ubuntu + containerd + kubeadm + keadm 기준의 KubeEdge 설치/패치/초기화 도구다.

이 디렉터리는 현재 PoC의 KubeEdge 기반 edge node 조인과 cloud/edge runtime 보정에 사용한다. 스크립트는 현재 경로에서 실행하는 것을 전제로 `./tools.sh`, `./tarball`, `./yamls`, `./patch`, `./config`를 참조한다.

```bash
cd /path/to/jinuk/kubeedge-tools
```

## 기존 클러스터 VPN 설정 재배포

현재 네트워크 기준은 `config/wireguard-network.json`이다. 새로 초기화하는 절차 대신 아래 경로로
기존 설정을 재배포한다. `setup-cloud.sh`, `kubeadm init`, `keadm init`, `patch-cloud.sh`는
기존 클러스터의 네트워크 재배포 단계가 아니다.

- Flannel: `kustomization.yaml` → 공통 RBAC/MTU + `config/flannel-interfaces.yaml` + cloud/edge DaemonSet.
  VPN 노드는 `wg0`, Tinker만 `192.168.0.7`. WireGuard MTU 1380, Pod MTU 1330, `OnDelete` 유지.
- CloudCore: `config/cloudcore-network-values.yaml`의 VPN·LAN·10.254 광고 주소.
- EdgeMesh: `config/edgemesh-values.yaml`의 VPN/LAN relay와 검증된 image digest.
- host: `/etc/wireguard/wg0.conf`, kubelet/EdgeCore, containerd certs.d, systemd 경로 복원 설정은
  각 host에 영속화되어 있다. Kubernetes manifest 재배포가 host 설정이나 개인 키를 생성하지 않는다.

저장소 root에서 먼저 서버 검증만 실행한다. 기존 Pod는 재시작하지 않는다.

```bash
rtk proxy bash kubeedge-tools/install-flannel-cloud.sh --check
rtk proxy bash kubeedge-tools/install-flannel-edge.sh --check
rtk proxy kubectl --context=kubernetes-admin@kubernetes apply --dry-run=server -k kubeedge-tools
# 검토한 구성 적용:
rtk proxy bash kubeedge-tools/install-flannel-cloud.sh --apply
rtk proxy bash kubeedge-tools/install-flannel-edge.sh --apply
```

설치 스크립트는 기본적으로 `--check`이며, 어느 작업 디렉터리에서 실행해도 같은 파일을 사용한다.
`OnDelete`에서는 적용만으로 기존 Pod가 바뀌지 않는다. 차이가 있을 때만 정확한 노드의 Flannel
Pod를 하나씩 교체하고 통신을 확인한다. 신규 node는 가입 전에 inventory와 interface map에
추가한다. map에 이름이 없으면 Flannel은 잘못된 인터페이스를 선택하지 않고 시작을 중단한다.

Helm은 **현재 설치된 것과 같은 name/version/appVersion의 완전한 로컬 chart**를 준비한다.
EdgeMesh는 `charts/agent` 등 dependency가 포함되어야 한다. 아래 도구는 live resource를
post-renderer로 보존하므로 오래된 release values가 image·PSK·설정을 덮지 않는다.
일반 `helm upgrade --reuse-values`만 실행하는 방식으로 대체하지 않는다.

```bash
rtk proxy sudo python3 kubeedge-tools/redeploy_network_helm.py cloudcore --chart /path/to/cloudcore-chart
rtk proxy sudo python3 kubeedge-tools/redeploy_network_helm.py edgemesh --chart /path/to/edgemesh.tgz
# 서버 dry-run 검토 후 같은 명령에 --apply 추가
```

운영자 Python 의존성은 `requirements-network-operator.txt`에 있다.
이 도구는 기존 release만 지원하고 기본은 서버 dry-run이다. 적용 시 live baseline revision을
먼저 만든 뒤 network values를 반영한다. 전체 Helm payload와 인증 정보는 root 전용
`/var/backups/kubeedge/`에만 저장한다. 이미지 변경·relay 삭제는 이 도구의 범위가 아니다.
CloudCore 인증서는 별도 권위이며 새 주소가 필요하면 인증서 SAN 검증을 먼저 한다.
현재 VPN SAN은 이미 반영되어 있다. 네트워크 값이 같으면 Pod 재시작은 필요 없다.

남겨둔 LAN 값은 용도가 있다. WireGuard `Endpoint=192.168.0.56:51820`은 터널 바깥 주소이고,
이미지의 `192.168.0.56:5000/...`는 기존 registry namespace다. 다운로드는 VPN mirror 우선이다.
Tinker와 복구용 주소까지 일괄 치환하면 연결을 끊을 수 있다.

[실장비 전환·복구 절차](../docs/ops/WireGuard-노드-통신-전환.md)를 함께 따른다.

## 대상 환경

현재 기준:

- Cloud/control-plane 운영 주소: `10.77.0.1` (WireGuard), LAN 복구·VPN 외부 전송 주소: `192.168.0.56`
- Edge: Jetson/Raspberry Pi 5/ASUS Tinker Edge R 계열 edge node
- Runtime: `containerd`
- Kubernetes: `kubeadm` 기반 클러스터
- KubeEdge: `keadm`, live CloudCore/기존 edge와 같은 버전을 명시적으로 지정
- Pod CIDR: `10.244.0.0/16`

검증 기준으로 사용한 버전:

- Kubernetes Client/Server: `v1.31.14`
- Edge Node Kubernetes: `v1.32.10-kubeedge-v1.23.0`
- Container Runtime: `containerd://1.7.x` 또는 검증된 `2.2.x`

KubeEdge 버전은 필요하면 스크립트 실행 시 환경변수로 바꾼다.

```bash
sudo KUBEEDGE_VERSION=v1.23.0 ./setup-cloud.sh
sudo KUBEEDGE_VERSION=v1.23.0 ./setup-edge.sh
```

## 파일 역할

| 파일 | 실행 위치 | 역할 |
|---|---|---|
| `download.sh` | 인터넷/이미지 pull 가능 호스트 | `crictl`, CNI plugin, flannel, pause, nginx tarball 준비 |
| `setup-cloud.sh` | cloud node | `crictl`, CNI, keadm 설치, kubelet 전제조건 보정 |
| `setup-edge.sh` | edge node | `crictl`, CNI, keadm 설치, 로컬 이미지 tarball load |
| `patch-cloud.sh` | cloud node | legacy KubeEdge dynamic controller가 명시적으로 필요할 때만 보정 |
| `onboard-edge-lan.sh` | 신규 LAN edge node | ETRI hostname, kernel/sysctl, keadm join, EdgeCore YAML 보정을 한 흐름으로 수행 |
| `patch-edge.sh` | edge node | hostname/CloudCore/containerd/metaServer를 생성된 EdgeCore YAML에 검증 후 보정 |
| `patch_edgecore_config.py` | edge node/테스트 | v1alpha1/v1alpha2 config shape를 확인하고 필요한 scalar만 원자적으로 변경 |
| `finalize-edge-lan.sh` | cloud operator host | node label, edge Flannel, EdgeMesh, node-exporter, dashboard 관측 검증 |
| `config/edgemesh-values.yaml` | cloud operator host | 현재 relay와 digest를 고정한 non-secret EdgeMesh Helm values |
| `setup-wireguard-cloud.sh` | cloud node | 신규 WireGuard interface 준비. 기본 미리보기, `--apply`로 적용; 기존 설정 보존 |
| `setup-wireguard-edge.sh` | worker/edge node | 신규 WireGuard interface 준비. 기본 미리보기, `--apply`로 적용; 기존 설정 보존 |
| `wireguard_peer.py` | VPN host | 기존 peer 미리보기·선택 변경, live sync 실패 시 복구 |
| `networkctl.py` | operator | 노드 주소 검증, live 관측, 노드별 Flannel·Helm 검토 파일 생성 |
| `host_network.py` | worker/edge node | 호스트 주소 전환, 5분 복구 타이머, 검증 후 commit |
| `onboard-vpn-node.sh` | 신규 worker/edge node | VPN·커널 점검 후 역할별 가입; 기본 미리보기 |
| `install-flannel-cloud.sh` | cloud node | cloud용 flannel DaemonSet 적용 |
| `install-flannel-edge.sh` | cloud node | edge용 flannel DaemonSet 적용 |
| `kubeedge_k8s_full_reset.sh` | 대상 node | KubeEdge/Kubernetes/CNI 상태 제거 후 재설치 준비 |
| `clean.sh` | 작업 디렉터리 | 다운로드한 tarball 제거 |
| `deploy.yaml` | cloud node | 과거 metrics-server 데모 manifest; 현재 monitoring 설치 경로가 아님 |
| `cloudcore-feature-rbac.yaml` | cloud node | KubeEdge feature RBAC 참고자료; 일반 node join에는 적용하지 않음 |

## 사전 조건

Cloud node:

- `containerd`가 설치되어 있고 실행 중이어야 한다.
- `kubelet`, `kubeadm`, `kubectl`은 미리 설치되어 있어야 한다.
- `setup-cloud.sh`는 Ubuntu에서 Kubernetes 패키지를 직접 설치하지 않는다. 없으면 중단한다.
- `sudo` 권한이 필요하다.
- 외부 edge node를 VPN으로 붙일 때는 cloud node의 `UDP 51820`이 외부에서 접근 가능해야 한다.

Edge node:

- `containerd`가 설치되어 있고 실행 중이어야 한다.
- cloud node의 `10000` 포트로 접근 가능해야 한다.
- `/etc/kubeedge/config/edgecore.yaml`은 `keadm join` 이후 생성된다.
- `sudo` 권한이 필요하다.

공통:

- CNI는 하나만 사용한다. flannel과 calico를 섞지 않는다.
- 이 도구는 현재 containerd 기준이다. Docker 잔재 제거는 reset 스크립트 옵션으로만 다룬다.
- 방화벽, NAT, 보안 장비가 cloudcore/edgecore 통신을 막지 않아야 한다.
- 2026-09-09 기존 6대의 Node InternalIP·Flannel을 `10.77.0.0/24`로 전환했다. Tinker만 `192.168.0.7`을 유지하며 hub 반환 경로를 사용한다. API·CloudHub·EdgeMesh·모니터링과 센서 12개 freshness를 검증했다. AGX는 wireguard-go를 사용한다. 외부 공인 endpoint와 실제 원격 worker/edge 가입, 재부팅 시험은 아직 남아 있다. [WireGuard 전환 운영 절차](../docs/ops/WireGuard-노드-통신-전환.md)를 따른다.

필수 명령 확인:

```bash
containerd --version
kubeadm version
kubectl version --client
```

## 1. 설치 자산 준비

인터넷 접근과 이미지 pull이 가능한 호스트에서 실행한다.

```bash
cd /path/to/jinuk/kubeedge-tools
./download.sh
```

생성/사용되는 주요 파일:

```text
tarball/crictl-v1.20.0-linux-{amd64,arm64}.tar.gz
tarball/cni-plugins-linux-{amd64,arm64}-v0.9.0.tgz
tarball/flannel-{amd64,arm64}.tar
tarball/flannel-cni-plugin-{amd64,arm64}.tar
tarball/kubeedge-pause-{amd64,arm64}.tar
tarball/nginx-{amd64,arm64}.tar
```

Edge node에서 인터넷 pull이 어렵다면 `tarball/` 디렉터리를 edge node의 같은 경로로 복사한다.

## 2. Cloud Node 설치

Cloud node에서 실행한다.

```bash
cd /path/to/jinuk/kubeedge-tools
sudo KUBEEDGE_VERSION=v1.23.0 ./setup-cloud.sh
```

`setup-cloud.sh`가 하는 일:

- `crictl` 설치
- CNI plugin 설치
- bridge netfilter / ip forward / swap off 적용
- `kubelet` enable/start
- `keadm` 설치
- `ntpdate cn.pool.ntp.org`

아래 초기화는 별도로 승인된 신규 구축 전용이다. 먼저 hub의 `wg0=10.77.0.1`과 시작 순서를 준비한다.
기존 클러스터에서는 실행하지 않는다.

```bash
sudo kubeadm init \
  --apiserver-advertise-address=10.77.0.1 \
  --control-plane-endpoint=10.77.0.1:6443 \
  --pod-network-cidr=10.244.0.0/16

mkdir -p "$HOME/.kube"
sudo cp /etc/kubernetes/admin.conf "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
```

control-plane에서도 workload를 돌릴 수 있게 taint를 제거한다.

```bash
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl taint nodes --all node-role.kubernetes.io/master- || true
```

CloudCore를 초기화한다.

```bash
KUBEEDGE_VERSION=v1.23.0
sudo keadm init \
  --advertise-address=10.77.0.1 \
  --kubeedge-version="${KUBEEDGE_VERSION#v}"
```

`patch-cloud.sh`는 KubeEdge dynamic controller가 별도로 필요한 기존 설치에서만 사용한다.
현재 PoC의 신규 node join에는 필요하지 않으며, KubeEdge Device를 EdgeX 물리 디바이스
권위와 병행하는 용도로 활성화하지 않는다.

```bash
sudo ./patch-cloud.sh
```

`patch-cloud.sh`는 설치 방식에 따라 둘 중 하나로 동작한다.

- file mode: `/etc/kubeedge/config/cloudcore.yaml` 패치
- configmap mode: `kubeedge/cloudcore` ConfigMap의 `dynamicController.enable`을 `true`로 변경하고 cloudcore Deployment를 `Recreate` 전략으로 재시작

cloudcore hostPort 충돌이 생기면 오래된 pod를 지우고 재확인한다.

```bash
kubectl -n kubeedge get pods -o wide
kubectl -n kubeedge delete pod -l k8s-app=kubeedge
kubectl -n kubeedge rollout status deploy/cloudcore --timeout=180s
```

### v1.23.1 metrics stream 오류 보정

KubeEdge v1.23 계열 CloudCore는 정상적인 edge metrics stream 종료를 오류로 반환해
`Failed to get metrics ... find edge peer done` 로그를 반복할 수 있다. 또한 일부 정상 종료
경로에서 API server connection 정리가 누락될 수 있다. 이 저장소는 v1.23.1 소스 기준
패치와 재현 가능한 빌드 스크립트를 제공한다.

```bash
cd kubeedge-tools
sudo -E ./build-cloudcore-metrics-fix.sh
```

기본 출력 이미지는 `192.168.0.56:5000/cloudcore:v1.23.1-metricsfix.1`이다. 빌드 시
`cloud/pkg/cloudstream` 단위 테스트를 먼저 통과해야 이미지를 빌드하고 레지스트리에
push한다. 운영 배포에는 tag 대신 push 결과의 digest를 고정한다.

```bash
kubectl -n kubeedge patch deploy/cloudcore --type='json' \
  -p='[{"op":"remove","path":"/spec/strategy/rollingUpdate"}]' || true
kubectl -n kubeedge patch deploy/cloudcore \
  -p='{"spec":{"strategy":{"type":"Recreate"}}}'
kubectl -n kubeedge set image deploy/cloudcore \
  cloudcore=192.168.0.56:5000/cloudcore@sha256:474b4495c2b69a1c0556436c53a06458977fe7fd7b2e25471e84b042e55e77d4
kubectl -n kubeedge rollout status deploy/cloudcore --timeout=180s
```

`Recreate`는 hostNetwork/hostPort를 쓰는 단일 CloudCore의 rolling update 포트 충돌을
피하기 위한 운영 조건이다.

cloudcore를 control-plane node에 고정해야 할 때는 아래 패치를 적용한다.

```bash
kubectl -n kubeedge patch deploy cloudcore --type='merge' -p '{
  "spec": {
    "template": {
      "spec": {
        "nodeSelector": {
          "node-role.kubernetes.io/control-plane": ""
        },
        "tolerations": [
          {
            "key": "node-role.kubernetes.io/control-plane",
            "operator": "Exists",
            "effect": "NoSchedule"
          }
        ]
      }
    }
  }
}'
```

cloud flannel을 적용한다.

```bash
rtk proxy bash ./install-flannel-cloud.sh --apply
```

아래 manifest는 외부 원본 저장소 보존용 참고자료다. 현재 cluster의 설치 방식과 버전을
검증하고 해당 기능이 명시적으로 필요할 때만 별도 변경으로 적용한다. 특히
`deploy.yaml`의 metrics-server 이미지는 현재 monitoring 기준이 아니다.

```bash
kubectl apply -f cloudcore-feature-rbac.yaml
kubectl apply -f deploy.yaml
```

## 3. LAN Edge Node 설치 (명시적 LAN 예외 전용)

현재 기본 가입 경로는 `onboard-vpn-node.sh`다. 아래 예시는 Tinker처럼 LAN 유지가
명시된 노드에만 사용하며, VPN 노드의 재배포 설정으로 복사하지 않는다.

신규 edge node는 조인 전에 hostname을 다음 형식으로 확정한다.

```text
etri-devNNNN-jetorn  # Jetson
etri-devNNNN-raspi5  # Raspberry Pi 5
etri-devNNNN-tedger  # ASUS Tinker Edge R
```

`NNNN`은 live cluster에서 사용하지 않는 4자리 번호다. 2026-09-09 실측상 `0001`~`0005`가 사용 중이므로 다음 후보는 `0006`이지만, 실행 직전에 다시 확인한다. Kubernetes Node 이름은 rename할 수 있는 일반 필드가 아니므로 hostname을 바꾸려면 반드시 `keadm join` 전에 수행한다.

cloud operator host에서 hostname 중복과 live version을 먼저 확인한다.

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name
helm list -n kubeedge
kubectl get nodes -l node-role.kubernetes.io/edge \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.kubeletVersion}{"\n"}{end}'
```

각 신규 LAN edge node에서 다음 변수를 실제 값으로 설정한다.

```bash
cd /path/to/jinuk/kubeedge-tools
sudo -E env \
  EDGE_NODE_NAME=etri-dev0006-raspi5 \
  EDGE_NODE_CLASS=raspi \
  CLOUDCORE_HOST=192.168.0.56 \
  KUBEEDGE_VERSION=v1.23.0 \
  CONFIRM_UNIQUE_NODE=etri-dev0006-raspi5 \
  ./onboard-edge-lan.sh
```

containerd의 `SystemdCgroup=true`를 사용하는 장비는 위 환경 변수에
`KUBEEDGE_CGROUP_DRIVER=systemd`를 추가한다. 가입 도구의 기본값은 기존과 같은
`cgroupfs`이며, 실제 런타임과 일치해야 설치용 컨테이너가 시작된다.
`onboard-vpn-node.sh`에도 같은 환경 변수를 전달한다.

`onboard-edge-lan.sh`가 하는 일:

- hostname 형식/하드웨어 class/CloudCore private LAN IP 검증
- 기존 EdgeCore 상태가 없는 신규 host인지 확인
- hostname을 조인 전에 설정
- `br_netfilter`, `xt_physdev`, bridge netfilter, IP forwarding 영속 설정
- CloudCore `10000`, `10002`, `10004` 실제 TCP 연결 확인
- `crictl` 설치
- CNI plugin 설치
- flannel / kubeedge pause / nginx 이미지 tarball load
- `ntpdate` 설치
- `keadm` 설치
- `ntpdate cn.pool.ntp.org`
- hidden prompt로 join token 입력 후 `keadm join`
- 생성된 `/etc/kubeedge/config/edgecore.yaml`의 hostname, CloudCore LAN endpoint, containerd, metaServer 검증/보정

cloud node에서 join token을 발급한다.

```bash
keadm gettoken
```

발급한 token은 파일/문서/로그에 저장하지 않고 `onboard-edge-lan.sh`의 hidden prompt에만 입력한다.

내부에서 호출되는 `patch-edge.sh`는 다음 값을 보정하고 edgecore를 재시작한다.

- `hostnameOverride: <EDGE_NODE_NAME>`
- `edgeHub.websocket.server: <CLOUDCORE_HOST>:10000`
- `edgeHub.httpServer: https://<CLOUDCORE_HOST>:10002`
- `edgeStream.server: <CLOUDCORE_HOST>:10004`
- `remoteImageEndpoint: unix:///run/containerd/containerd.sock`
- `remoteRuntimeEndpoint: unix:///run/containerd/containerd.sock`
- `runtimeType: remote`
- `tailoredKubeletConfig.containerRuntimeEndpoint: unix:///run/containerd/containerd.sock`
- `tailoredKubeletConfig.imageServiceEndpoint: unix:///run/containerd/containerd.sock`
- `metaServer.enable: true`

cloud operator host에서는 label과 DaemonSet/dashboard 관측을 마무리한다.

```bash
KUBE_CONTEXT=kubernetes-admin@kubernetes \
EDGE_NODE_NAME=etri-dev0006-raspi5 \
EDGE_NODE_CLASS=raspi \
CLOUDCORE_HOST=192.168.0.56 \
  ./finalize-edge-lan.sh
```

이 스크립트는 `environment=edge`, 검증된 hardware class만 추가하고 legacy `edge.device/mapper` label은 제거한다. 이어서 edge Flannel, 기존 EdgeMesh agent, node-exporter와 `/state/nodes` 관측을 확인한다.

### EdgeCore config 수동 확인/수정

아래 LAN 도구는 LAN 예외 노드용이다. 신규 VPN node는 `onboard-vpn-node.sh`와 VPN 전환 운영 절차를 사용한다.
LAN 예외에서는 `patch-edge.sh` 실행이 기본 경로다. 그래도 edge node 조인 후 pod 생성, image pull, DNS, edge flannel 경로가 이상하면 edge node에서 `/etc/kubeedge/config/edgecore.yaml`을 직접 확인한다.

```bash
sudo sed -n '1,220p' /etc/kubeedge/config/edgecore.yaml
sudo grep -nE 'remoteImageEndpoint|remoteRuntimeEndpoint|runtimeType|metaServer|websocket|server' /etc/kubeedge/config/edgecore.yaml
```

KubeEdge 구버전 config shape에서는 아래 값이 맞아야 한다.

```yaml
modules:
  edged:
    remoteImageEndpoint: unix:///run/containerd/containerd.sock
    remoteRuntimeEndpoint: unix:///run/containerd/containerd.sock
    runtimeType: remote
  metaManager:
    metaServer:
      enable: true
```

현재 Jetson `etri-dev0001-jetorn`에서 확인한 KubeEdge `v1.23.0` config shape는 아래 쪽이다. 이 버전에서는 containerd endpoint가 `tailoredKubeletConfig` 아래에 있다.

```yaml
apiVersion: edgecore.config.kubeedge.io/v1alpha2
edgecoreVersion: v1.23.0
modules:
  deviceTwin:
    dmiSockPath: /etc/kubeedge/
    enable: true
  edgeHub:
    httpServer: https://10.77.0.1:10002
    projectID: <PROJECT_ID>
    websocket:
      enable: true
      server: 10.77.0.1:10000
  edgeStream:
    enable: true
    server: 10.77.0.1:10004
  edged:
    customInterfaceName: wg0
    hostnameOverride: etri-dev0001-jetorn
    podSandboxImage: kubeedge/pause:3.6
    tailoredKubeletConfig:
      clusterDNS:
      - 169.254.96.16
      containerRuntimeEndpoint: unix:///run/containerd/containerd.sock
      imageServiceEndpoint: unix:///run/containerd/containerd.sock
      registerNode: true
  eventBus:
    enable: true
    mqttMode: 2
    mqttServerExternal: tcp://127.0.0.1:1883
    mqttServerInternal: tcp://127.0.0.1:1884
  metaManager:
    contextSendModule: websocket
    enable: true
    metaServer:
      dummyServer: 169.254.30.10:10550
      enable: true
      server: 127.0.0.1:10550
  serviceBus:
    enable: true
    server: 127.0.0.1
```

운영 VPN edge는 `customInterfaceName: wg0`와 다음 VPN 주소를 사용한다.
Tinker처럼 명시적으로 유지한 LAN edge만 `192.168.0.56`을 사용한다.

- `modules.edgeHub.websocket.server: 10.77.0.1:10000`
- `modules.edgeHub.httpServer: https://10.77.0.1:10002`
- `modules.edgeStream.server: 10.77.0.1:10004`

수동 수정이 필요하면 edge node에서 편집 후 edgecore를 재시작한다.

```bash
sudo vi /etc/kubeedge/config/edgecore.yaml
sudo systemctl restart edgecore
sudo systemctl status edgecore --no-pager -n 80
```

edge node가 cluster에 보이는지 cloud node에서 확인한다.

```bash
kubectl get nodes -o wide
```

현재 node label을 확인한다. 신규 node에는 legacy mapper label을 추가하지 않는다.

```bash
kubectl label node <EDGE_NODE_NAME> environment=edge --overwrite
kubectl label node <EDGE_NODE_NAME> edge.device/class=<jetson-or-raspi> --overwrite
```

## 4. Edge Flannel 배포

Cloud node에서 실행한다.

```bash
cd /path/to/jinuk/kubeedge-tools
rtk proxy bash ./install-flannel-edge.sh --apply
```

정상 확인:

```bash
kubectl -n kube-system get ds -o wide | grep flannel
kubectl -n kube-system rollout status ds/kube-flannel-cloud-ds --timeout=180s
kubectl -n kube-system rollout status ds/kube-flannel-edge-ds --timeout=180s
```

## 5. EdgeMesh 설치

EdgeMesh는 cluster에 한 번 설치한 DaemonSet이며 신규 edge node마다 다시 설치하지 않는다. 현재 Helm release의 non-secret 기준값은 `config/edgemesh-values.yaml`이다. 신규 node가 edge 역할로 등록되면 기존 DaemonSet이 자동 배치되어야 한다.

아래 설치·kube-proxy 변경 명령은 EdgeMesh가 없는 새 cluster를 구축하는 경우에만
검토한다. 현재 운영 cluster에 신규 node 하나를 추가할 때는 실행하지 않는다.

```bash
kubectl taint nodes --all node-role.kubernetes.io/master- || true
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true

kubectl patch daemonset kube-proxy -n kube-system -p \
  '{"spec":{"template":{"spec":{"affinity":{"nodeAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":{"nodeSelectorTerms":[{"matchExpressions":[{"key":"node-role.kubernetes.io/edge","operator":"DoesNotExist"}]}]}}}}}}}'

kubectl label services kubernetes service.edgemesh.kubeedge.io/service-proxy-name="" --overwrite

PSK=$(openssl rand -base64 32)
helm install edgemesh --namespace kubeedge \
  --set agent.psk="$PSK" \
  -f config/edgemesh-values.yaml \
  https://raw.githubusercontent.com/kubeedge/edgemesh/main/build/helm/edgemesh.tgz
unset PSK
```

기존 release 재배포는 위의 `redeploy_network_helm.py`를 사용한다. `--reuse-values`만으로는
현재 live image·PSK·runtime patch가 보존되지 않는다. relay 기준은
`etri-ser0001-cg0msb`, 광고 주소는 `192.168.0.56`과 `10.77.0.1`이다.

릴레이 노드명이 실제 control-plane node 이름과 다르면 live 상태와 Helm values를 비교하고 `config/edgemesh-values.yaml`을 먼저 수정한 뒤 Helm으로 반영한다. live ConfigMap만 직접 편집하지 않는다.

확인:

```bash
kubectl -n kubeedge get pods -o wide | grep edgemesh
kubectl -n kube-system get ds kube-proxy -o wide
kubectl -n kubeedge get pods \
  --field-selector spec.nodeName=<EDGE_NODE_NAME> -l kubeedge=edgemesh-agent
```

## 6. 설치 검증

Cloud node에서 실행한다.

```bash
kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl get ds -A -o wide
kubectl -n kubeedge get pods -o wide
```

정상 기준:

- cloud node와 edge node가 `Ready`
- `cloudcore`가 `Running`
- `kube-flannel-cloud-ds`와 `kube-flannel-edge-ds`가 정상
- edge node의 `edgecore` systemd service가 active
- container runtime이 `containerd`로 보임

Edge node에서 실행:

```bash
systemctl status edgecore --no-pager -n 80
crictl info
```

Cloud node에서 현재 edge label과 system DaemonSet을 확인한다.

```bash
kubectl get nodes --show-labels | grep 'environment=edge'
kubectl -n kube-system get pods -l app=flannel -o wide
kubectl -n kubeedge get pods -l kubeedge=edgemesh-agent -o wide
```

## 7. 디버그

KubeEdge 공식 debug 문서:

- https://kubeedge.io/docs/advanced/debug/

자주 보는 로그:

```bash
# Cloud node
kubectl -n kubeedge logs deploy/cloudcore --tail=200
kubectl -n kubeedge describe deploy/cloudcore

# Edge node
sudo journalctl -u edgecore -n 200 --no-pager
sudo sed -n '1,220p' /etc/kubeedge/config/edgecore.yaml
```

cloudcore pending/port conflict:

```bash
kubectl -n kubeedge get pods -o wide
kubectl -n kubeedge delete pod -l k8s-app=kubeedge
kubectl -n kubeedge rollout status deploy/cloudcore --timeout=180s
```

edgecore runtime endpoint 확인:

```bash
grep -nE 'remoteImageEndpoint|remoteRuntimeEndpoint|runtimeType|metaServer' /etc/kubeedge/config/edgecore.yaml
```

## 8. 초기화 / 재설치

주의: `kubeedge_k8s_full_reset.sh`는 KubeEdge, Kubernetes, CNI, kubeconfig, network interface, iptables 상태를 제거한다. 재설치가 목적일 때만 실행한다.

containerd 기준:

```bash
sudo ./kubeedge_k8s_full_reset.sh --runtime containerd
```

Docker 잔재까지 같이 정리해야 하면:

```bash
sudo ./kubeedge_k8s_full_reset.sh --runtime both
```

Calico를 사용했던 노드에서 flannel로 전환하는 경우:

```bash
sudo ./kubeedge_k8s_full_reset.sh \
  --runtime containerd \
  --cleanup-calico-k8s \
  --cleanup-calico-crd
```

nftables까지 비워야 하는 경우에만 추가한다.

```bash
sudo ./kubeedge_k8s_full_reset.sh --runtime containerd --flush-nft
```

다운로드 tarball만 제거:

```bash
./clean.sh
```

## 9. 출처

- 원문 제목: KubeEdge Deployment Guide
- 원문 링크: https://docs.openeuler.org/en/docs/24.03_LTS_SP1/edge_computing/kube_edge/kube_edge_deployment_guide.html#cluster-overview
- 출처: openEuler community
- 수정 요약: Ubuntu + containerd + kubeadm + keadm 환경과 현재 PoC 스크립트 흐름에 맞춰 재구성
- KubeEdge Advanced Debug: https://kubeedge.io/docs/advanced/debug/

## 10. 라이선스

- 문서(README, `docs/`): CC BY-SA 4.0
  - https://creativecommons.org/licenses/by-sa/4.0/
  - 본 문서 및 파생 문서는 동일조건(CC BY-SA 4.0)으로 배포
- 코드/스크립트(그 외 파일): 루트 [LICENSE](LICENSE)의 Apache-2.0 적용

참고:

- [docs/ATTRIBUTION.md](docs/ATTRIBUTION.md)
- [docs/LICENSE-CC-BY-SA-4.0.md](docs/LICENSE-CC-BY-SA-4.0.md)


## VPN 재배포 설정 검증 (2026-09-09)

- cloud/edge 설치 진입점 및 `kubectl apply --dry-run=server -k kubeedge-tools` 통과.
- live Flannel DaemonSet과 재배포 결과의 spec은 이름 있는 목록의 순서를 제외하면 동일하다.
- CloudCore·EdgeMesh는 실제 설치 chart와 live snapshot 보존 post-renderer로 서버 dry-run 통과.
- 자동시험 41개: MTU/interface inventory 일치, 중복 resource 방지, 다른 작업 디렉터리 실행,
  기본 dry-run, 기존 image/PSK/runtime 보존 및 주소 삭제·image 변경 거부를 포함한다.
- 이번 정리는 저장소 설정과 재배포 경로 정리다. 운영 release 변경·Pod 재시작을 실행하지 않았다.

```bash
rtk proxy uv run --no-project --with pytest --with pyyaml --with tomli --with cryptography python -m pytest -q kubeedge-tools/tests
```
