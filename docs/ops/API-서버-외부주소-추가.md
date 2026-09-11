# API 서버의 10.254 주소 인증서 준비

2026-09-09 14:34 KST, 사용자 승인으로 현재 control-plane의 API 서버 인증서에
`10.254.192.217` SAN을 추가했다. 기존 IP·DNS SAN과 CA는 유지했다.

## 반영과 확인

- 실행 파일: `tools/add-apiserver-san.py` (기본은 조회, `--apply`는 호스트 root 필요).
- 격리된 시험 CA로 인증서 생성, 기존 SAN 보존과 추가 SAN, CA 검증을 먼저 확인했다.
- 기존 인증서·키와 kubeadm ConfigMap 백업:
  `/var/backups/kubernetes/apiserver-san-20260909T053411Z` (호스트 root 전용).
- 실제 `192.168.0.56:6443` TLS 연결에서 CA 검증과
  `server_hostname=10.254.192.217` 이름 검증 성공.
- `/readyz` 응답 `ok`, API 서버 컨테이너 Ready 확인.
- `kube-system/kubeadm-config`의 `apiServer.certSANs`에도 추가 주소와 기존 SAN을 기록했다.
- 기존 kubeconfig, `controlPlaneEndpoint`, `kube-public/cluster-info`의 가입 안내 주소는
  변경하지 않았다. 외부 주소의 네트워크 경로가 검증되지 않았기 때문이다.

## 남은 네트워크 작업

`10.254.192.217`은 이 서버 NIC에 직접 할당된 주소가 아니다. 게이트웨이가 이 주소를
받는 구조라면 TCP `10.254.192.217:6443`을 `192.168.0.56:6443`으로 전달해야 한다.
게이트웨이 소유권과 실제 NAT 규칙은 아직 확인하지 않았다.

서버 내부에서 `10.254.192.217:6443` 접속은 시간 초과였다. NAT loopback 미지원일 수도
있으므로 실제 새 워커가 있는 네트워크에서 확인해야 한다. 인증서 준비 완료를 외부
접속 또는 워커 가입 완료로 해석하지 않는다.

포트 경로 확보 후 외부 워커의 discovery/bootstrap이 내부 `192.168.0.56` 주소로 돌아가지
않도록 가입 설정을 별도로 검증한다. 일반 Kubernetes 워커의 kubelet·CNI/Pod 통신 경로도
API 서버 접속과 별도로 확인한다.

EdgeMesh 중계 주소는 당시 `192.168.0.56`만 등록돼 있었으며,
`10.254.192.217:20006` 연결도 별도 미검증 상태다. 이번 작업은 EdgeMesh를 변경하지 않았다.

참고: [kubeadm 인증서 관리](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/),
[API 서버 인증서 생성](https://kubernetes.io/docs/reference/setup-tools/kubeadm/generated/kubeadm_init/kubeadm_init_phase_certs_apiserver/).
