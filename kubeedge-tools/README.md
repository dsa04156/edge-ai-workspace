# KubeEdge Tools

Ubuntu + containerd + kubeadm + keadm 기준의 KubeEdge 설치/패치/초기화 도구다.

이 디렉터리는 현재 PoC의 KubeEdge 기반 edge node 조인과 cloud/edge runtime 보정에 사용한다. 스크립트는 현재 경로에서 실행하는 것을 전제로 `./tools.sh`, `./tarball`, `./yamls`, `./patch`, `./config`를 참조한다.

```bash
cd /home/etri/jinuk/kubeedge-tools
```

## 대상 환경

현재 기준:

- Cloud/control-plane: `192.168.0.56`
- Edge: Jetson/Raspberry Pi 계열 edge node
- Runtime: `containerd`
- Kubernetes: `kubeadm` 기반 클러스터
- KubeEdge: `keadm`, 기본 `v1.22.0`
- Pod CIDR: `10.244.0.0/16`

검증 기준으로 사용한 버전:

- Kubernetes Client/Server: `v1.31.14`
- Edge Node Kubernetes: `v1.31.12-kubeedge-v1.22.0`
- Container Runtime: `containerd://1.7.18`

KubeEdge 버전은 필요하면 스크립트 실행 시 환경변수로 바꾼다.

```bash
sudo KUBEEDGE_VERSION=v1.22.0 ./setup-cloud.sh
sudo KUBEEDGE_VERSION=v1.22.0 ./setup-edge.sh
```

## 파일 역할

| 파일 | 실행 위치 | 역할 |
|---|---|---|
| `download.sh` | 인터넷/이미지 pull 가능 호스트 | `crictl`, CNI plugin, flannel, pause, nginx tarball 준비 |
| `setup-cloud.sh` | cloud node | `crictl`, CNI, keadm 설치, kubelet 전제조건 보정 |
| `setup-edge.sh` | edge node | `crictl`, CNI, keadm 설치, 로컬 이미지 tarball load |
| `patch-cloud.sh` | cloud node | cloudcore `dynamicController.enable=true` 보정, Deployment 재시작 |
| `patch-edge.sh` | edge node | edgecore containerd endpoint, `runtimeType=remote`, `metaServer.enable=true` 보정 |
| `setup-wireguard-cloud.sh` | cloud node | 외부 edge join/통신용 WireGuard cloud endpoint 준비 |
| `setup-wireguard-edge.sh` | edge node | 기존 edge node에 WireGuard peer 설정 추가 |
| `install-flannel-cloud.sh` | cloud node | cloud용 flannel DaemonSet 적용 |
| `install-flannel-edge.sh` | cloud node | edge용 flannel DaemonSet 적용 |
| `kubeedge_k8s_full_reset.sh` | 대상 node | KubeEdge/Kubernetes/CNI 상태 제거 후 재설치 준비 |
| `clean.sh` | 작업 디렉터리 | 다운로드한 tarball 제거 |
| `deploy.yaml` | cloud node | metrics-server manifest |
| `cloudcore-feature-rbac.yaml` | cloud node | cloudcore feature RBAC 보강 |

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
- WireGuard를 사용할 때 기존 `192.168.0.x` node IP는 유지하고, VPN은 별도 대역(`10.77.0.0/24`)으로 추가한다.

필수 명령 확인:

```bash
containerd --version
kubeadm version
kubectl version --client
```

## 1. 설치 자산 준비

인터넷 접근과 이미지 pull이 가능한 호스트에서 실행한다.

```bash
cd /home/etri/jinuk/kubeedge-tools
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
cd /home/etri/jinuk/kubeedge-tools
sudo ./setup-cloud.sh
```

`setup-cloud.sh`가 하는 일:

- `crictl` 설치
- CNI plugin 설치
- bridge netfilter / ip forward / swap off 적용
- `kubelet` enable/start
- `keadm` 설치
- `ntpdate cn.pool.ntp.org`

Kubernetes control-plane이 아직 없으면 초기화한다.

```bash
sudo kubeadm init \
  --apiserver-advertise-address=192.168.0.56 \
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
sudo keadm init \
  --advertise-address=192.168.0.56 \
  --kubeedge-version=1.22.0
```

CloudCore 설정을 패치한다.

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
sudo ./install-flannel-cloud.sh
```

필요하면 cloudcore feature RBAC와 metrics-server를 적용한다.

```bash
kubectl apply -f cloudcore-feature-rbac.yaml
kubectl apply -f deploy.yaml
```

## 3. Edge Node 설치

각 edge node에서 반복한다.

```bash
cd /home/etri/jinuk/kubeedge-tools
sudo ./setup-edge.sh
```

`setup-edge.sh`가 하는 일:

- `crictl` 설치
- CNI plugin 설치
- flannel / kubeedge pause / nginx 이미지 tarball load
- `ntpdate` 설치
- `keadm` 설치
- `ntpdate cn.pool.ntp.org`

cloud node에서 join token을 발급한다.

```bash
keadm gettoken
```

edge node에서 join한다.

```bash
sudo keadm join \
  --cloudcore-ipport=192.168.0.56:10000 \
  --token=<TOKEN> \
  --kubeedge-version=1.22.0
```

join 이후 edgecore 설정을 containerd 기준으로 패치한다.

```bash
sudo ./patch-edge.sh
```

`patch-edge.sh`는 다음 값을 보정하고 edgecore를 재시작한다.

- `remoteImageEndpoint: unix:///run/containerd/containerd.sock`
- `remoteRuntimeEndpoint: unix:///run/containerd/containerd.sock`
- `runtimeType: remote`
- `tailoredKubeletConfig.containerRuntimeEndpoint: unix:///run/containerd/containerd.sock`
- `tailoredKubeletConfig.imageServiceEndpoint: unix:///run/containerd/containerd.sock`
- `metaServer.enable: true`

### EdgeCore config 수동 확인/수정

`patch-edge.sh` 실행이 기본 경로다. 그래도 edge node 조인 후 pod 생성, image pull, DNS, edge flannel 경로가 이상하면 edge node에서 `/etc/kubeedge/config/edgecore.yaml`을 직접 확인한다.

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
    httpServer: https://192.168.0.56:10002
    projectID: <PROJECT_ID>
    websocket:
      enable: true
      server: 192.168.0.56:10000
  edgeStream:
    enable: true
    server: 192.168.0.56:10004
  edged:
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

cloudcore 접속 정보도 join 대상 cloud IP를 가리켜야 한다. `keadm join --cloudcore-ipport=192.168.0.56:10000`로 생성된 설정이라면 다음 값들이 `192.168.0.56` 계열인지 확인한다.

- `modules.edgeHub.websocket.server: 192.168.0.56:10000`
- `modules.edgeHub.httpServer: https://192.168.0.56:10002`
- `modules.edgeStream.server: 192.168.0.56:10004`

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

현재 PoC에서 mqttvirtual mapper를 edge node에 배치하려면 node label도 확인한다.

```bash
kubectl label node <EDGE_NODE_NAME> environment=edge --overwrite
kubectl label node <EDGE_NODE_NAME> edge.device/mapper=mqttvirtual --overwrite
```

## 4. Edge Flannel 배포

Cloud node에서 실행한다.

```bash
cd /home/etri/jinuk/kubeedge-tools
sudo ./install-flannel-edge.sh
```

정상 확인:

```bash
kubectl -n kube-system get ds -o wide | grep flannel
kubectl -n kube-system rollout status ds/kube-flannel-cloud-ds --timeout=180s
kubectl -n kube-system rollout status ds/kube-flannel-edge-ds --timeout=180s
```

## 5. EdgeMesh 설치

EdgeMesh는 이 디렉터리의 스크립트가 아니라 수동 Helm 절차다. Cloud node에서 실행한다.

```bash
kubectl taint nodes --all node-role.kubernetes.io/master- || true
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true

kubectl patch daemonset kube-proxy -n kube-system -p \
  '{"spec":{"template":{"spec":{"affinity":{"nodeAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":{"nodeSelectorTerms":[{"matchExpressions":[{"key":"node-role.kubernetes.io/edge","operator":"DoesNotExist"}]}]}}}}}}}'

kubectl label services kubernetes service.edgemesh.kubeedge.io/service-proxy-name="" --overwrite

PSK=$(openssl rand -base64 32)
helm install edgemesh --namespace kubeedge \
  --set agent.psk="$PSK" \
  --set agent.relayNodes[0].nodeName=<CONTROL_PLANE_NODE_NAME> \
  --set agent.relayNodes[0].advertiseAddress="{192.168.0.56}" \
  https://raw.githubusercontent.com/kubeedge/edgemesh/main/build/helm/edgemesh.tgz
```

릴레이 노드명이 실제 control-plane node 이름과 다르면 수정한다.

```bash
kubectl edit configmap edgemesh-agent-cfg -n kubeedge
```

확인:

```bash
kubectl -n kubeedge get pods -o wide | grep edgemesh
kubectl -n kube-system get ds kube-proxy -o wide
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

Cloud node에서 mqttvirtual mapper까지 확인:

```bash
kubectl get nodes --show-labels | grep 'environment=edge'
kubectl get pods -n default -l app=mqttvirtual-mapper -o wide
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
