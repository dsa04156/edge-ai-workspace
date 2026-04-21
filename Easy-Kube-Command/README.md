# Easy Ubuntu
## 1. quick-cmds.sh
**Quick-Cmds**는 Kubernetes와 Ubuntu 작업을 빠르게 하기 위한 alias/함수 모음입니다.

## 설정 방법

아래 내용을 `~/.bashrc` 또는 `~/.bash_profile`에 추가하세요.

```bash
# quick-cmds.sh 경로는 환경에 맞게 수정
source /home/etri/jinuk/Easy-Kube-Command/quick-cmds.sh
```

적용:

```bash
source ~/.bashrc
```

### 설명 및 사용법

#### 기본 쉘 편의 기능

- `cd`: 디렉토리 이동 후 자동으로 `ls` 실행
  ```bash
  cd /path/to/dir
  ```
- `..`: 상위 디렉토리 이동
- `...`: 상위 2단계 디렉토리 이동
- `h`: `history` 조회
- `c`: `clear`

#### Kubernetes 기본 단축어

- `k`: `kubectl`
- `kg`: `kubectl get`
- `kga`: `kubectl get all`
- `kgp`: `kubectl get pod`
- `kgpa`: `kubectl get pod --all-namespaces`
- `kd`: `kubectl describe`
- `kf`: `kubectl apply -f`
- `kx`: `kubectl exec -it`
- `kr`: `kubectl rollout`
- `ks`: `kubectl get services`
- `ksc`: `kubectl get configmaps`
- `kdel`: `kubectl delete`
- `kcg`: `kubectl config get-contexts`
- `kcu`: `kubectl config use-context`

예시:

```bash
kg pod -n kube-system
kf deployment.yaml
kx <pod-name> -- /bin/bash
kcu my-cluster-context
```

#### Kedge 프로필 헬퍼

프로필별로 라벨/테인트를 빠르게 적용하는 함수입니다.

- 지원 프로필: `edge`, `cloud`, `gpu`
- 매핑:
  - `edge` -> label: `node-role.kubernetes.io/edge`, taint: `dedicated=edge:NoSchedule`
  - `cloud` -> label: `node-role.kubernetes.io/control-plane`, taint: `dedicated=cloud:NoSchedule`
  - `gpu` -> label: `nvidia.com/gpu.present`, taint: `dedicated=gpu:NoSchedule`

노드 라벨/테인트:

- `kl <node> <profile>`: 프로필 라벨 추가(덮어쓰기)
- `kdl <node> <profile>`: 프로필 라벨 제거
- `kt <node> <profile>`: 프로필 테인트 추가(덮어쓰기)
- `kut <node> <profile>`: 프로필 테인트 제거

예시:

```bash
kl worker-1 edge
kt worker-1 edge
kdl worker-1 edge
kut worker-1 edge
```

워크로드 pin/unpin:

- `kpin <kind> <name> <profile> -n <namespace>`
  - `spec.template.spec.affinity`와 `tolerations`를 patch해서 해당 프로필 노드로 스케줄되도록 고정
- `kunpin <kind> <name> <profile> -n <namespace>`
  - `affinity`만 제거
  - 현재 스크립트는 toleration 자동 제거를 하지 않음(메시지로 안내)

예시:

```bash
kpin deploy my-app edge -n default
kunpin deploy my-app edge -n default
```

주의:

- `kpin`/`kunpin`은 `Deployment`, `StatefulSet`, `DaemonSet`처럼 `spec.template`이 있는 리소스에서 사용해야 합니다.
- 잘못된 profile 입력 시 `unknown profile` 에러가 발생합니다.


## 2. install-docker.sh

**`install-docker.sh`** 스크립트는 Ubuntu 시스템에 Docker를 자동으로 설치하는 Bash 스크립트입니다. 이 스크립트는 Docker의 설치와 설정을 간소화하여, 사용자가 손쉽게 Docker를 사용할 수 있도록 도와줍니다.

---

#### 스크립트의 주요 기능:
1. **시스템 패키지 업데이트**: 최신 패키지 목록을 가져옵니다.
2. **필수 패키지 설치**: Docker 설치를 위해 필요한 패키지를 설치합니다.
3. **Docker GPG 키 추가**: Docker의 소프트웨어 저장소에서 패키지를 안전하게 가져올 수 있도록 GPG 키를 추가합니다.
4. **Docker 저장소 추가**: Docker 패키지를 설치할 수 있도록 공식 저장소를 추가합니다.
5. **Docker 설치**: Docker 엔진과 관련 도구를 설치합니다.
6. **Docker 서비스 상태 확인**: Docker 서비스가 정상적으로 실행되고 있는지 확인합니다.
7. **hello-world 컨테이너 실행**: Docker가 정상적으로 설치되었는지 확인하기 위해 간단한 컨테이너를 실행합니다.
8. **사용자를 Docker 그룹에 추가**: Docker 명령어를 sudo 없이 사용할 수 있도록 현재 사용자를 Docker 그룹에 추가합니다.

스크립트를 실행한 후, 사용자는 로그아웃하고 다시 로그인하여 Docker를 사용할 수 있습니다.
