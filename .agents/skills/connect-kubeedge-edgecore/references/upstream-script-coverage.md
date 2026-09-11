# `kubeedge-setup-scripts` 반영 범위

검토 원본은 `https://github.com/dsa04156/kubeedge-setup-scripts`의 `main`
commit `74cc440a8de7ccfde1db8a0241c7859433d180c7`이다. 외부 저장소는 역사적 출처이고,
실행 시에는 live cluster와 현재 checkout을 우선한다.

## 신규 LAN node에서 자동으로 이어지는 경로

1. `onboard-edge-lan.sh`가 hostname, hardware class, private CloudCore IP, swap,
   containerd, Calico 충돌, kernel module과 sysctl을 검사한다.
2. `setup-edge.sh`와 `tools.sh`가 architecture별 설치 자산과 정확한 `keadm` 버전을
   준비한다. 기존 `keadm` 버전이 다르면 요청 버전으로 교체한다.
3. hidden prompt로 token을 받아 `keadm join`을 실행한다.
4. `patch-edge.sh`와 `patch_edgecore_config.py`가 생성된 EdgeCore YAML의 hostname,
   CloudCore `10000/10002/10004`, containerd endpoint와 metaServer를 원자적으로
   보정하고 backup을 남긴다.
5. `finalize-edge-lan.sh`가 edge/agent role과 정확한 버전을 확인하고 현재 label을
   적용한 뒤 기존 Flannel, EdgeMesh, node-exporter와 dashboard 관측을 기다린다.

EdgeMesh와 Flannel은 cluster-wide DaemonSet이므로 신규 node마다 Helm install 또는
manifest 재적용을 하지 않는다. 새 edge role을 보고 기존 DaemonSet이 자동 배치되는
것이 정상 경로다.

## 외부 저장소 자산별 처리

| 외부 자산 | 현재 처리 |
|---|---|
| `README.md`, `docs/*`, `LICENSE` | 출처·라이선스를 유지하고 현재 hostname, v1.23, EdgeX 권위 경계로 최신화 |
| `download.sh`, `tools.sh`, `tarball/*`, `clean.sh` | arm64/amd64 오프라인 준비 경로로 유지. 번들 `crictl v1.20.0`, CNI `v0.9.0`은 과거 fallback이므로 사용 사실을 보고 |
| `setup-edge.sh` | 신규 node 흐름에 포함. KubeEdge version은 필수 입력이며 불일치 `keadm`을 교체 |
| `patch-edge.sh`, `patch/edgecore.yaml.patch` | 원본 patch 목적을 안전한 v1alpha1/v1alpha2 YAML patcher로 대체. 정적 patch는 보존만 함 |
| `install-flannel-edge.sh`, `yamls/kube-flannel-edge.yml` | 기존 edge DaemonSet의 선언 자료. 현재 manifest는 Flannel `v0.28.3`과 CNI plugin `v1.9.1-flannel1`로 보정 |
| `setup-cloud.sh`, `install-flannel-cloud.sh`, cloud Flannel YAML | 새 cluster 구축 또는 cloud 복구를 명시적으로 요청한 경우에만 사용. 기존 운영 cluster의 node 추가에는 실행하지 않음 |
| `patch-cloud.sh`, `patch/cloudcore.yaml.patch` | legacy dynamic controller가 실제로 필요한 경우만 사용. KubeEdge Device를 EdgeX와 병행하기 위해 활성화하지 않음 |
| `cloudcore-feature-rbac.yaml` | KubeEdge feature 참고자료. 일반 EdgeCore join에는 적용하지 않음 |
| `deploy.yaml` | metrics-server `v0.4.0` 과거 데모 자료. 현재 Prometheus/node-exporter 경로를 대체하지 않음 |
| EdgeMesh README 명령 | `config/edgemesh-values.yaml`의 현재 relay/digest와 기존 Helm release를 사용. 신규 node마다 PSK/release를 재생성하지 않음 |
| `yamls/nginx-deployment.yaml`, nginx tarballs | 선택적 workload smoke/demo 자산. join의 필수 성공 기준은 repository EdgeCore DNS smoke check |
| `config/isulad-*-daemon.json` | 빈 iSulad 참고파일. containerd 전용 현재 경로에서는 사용하지 않음 |
| `kubeedge_k8s_full_reset.sh` | 명시적인 rebuild 승인과 exact target 재확인 후에만 사용 |
| `.deploy.yaml.swp` | 원본에 포함된 editor 임시파일로 실행·설계 입력에서 제외 |

## 원본보다 강화된 항목

- `v1.22.0` 묵시적 기본값 제거와 live CloudCore/EdgeCore exact version match
- `jetson-desktop`, `rpi-worker-1` 대신 `etri-devNNNN-jetorn|raspi5|tedger` hostname
- 생성된 YAML shape 검증, atomic write, timestamp backup
- EdgeMesh relay `etri-ser0001-cg0msb` / `192.168.0.56`와 image digest 고정
- `br_netfilter`, `xt_physdev`, sysctl 영속화
- Calico/Flannel 혼용 거부
- legacy mapper label 제거
- Prometheus/node-exporter와 `state-aggregator /state/nodes` 확인
- KubeEdge node/workload 관리와 EdgeX physical-device authority 분리

원본 파일이 존재한다는 이유만으로 cloud 재설치, global taint 제거, kube-proxy patch,
dynamic controller 활성화, metrics-server 교체, nginx 배포, reset을 한꺼번에 수행하지 않는다.
현재 node 추가에 필요한 경로와 cluster-wide 변경을 분리해야 한다.
