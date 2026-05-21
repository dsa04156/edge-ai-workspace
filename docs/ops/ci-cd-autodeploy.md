# CI/CD 자동 배포 기준

## 목적

이 문서는 현재 KubeEdge 혼합 디바이스 edge AI 운영 가시화 PoC에서 GitHub Actions와 Argo CD를 함께 사용해 새 이미지를 자동 반영하는 기준을 정리한다.

현재 자동 배포 대상은 운영 데모 경로와 문서 확인에 직접 필요한 구성 요소다.

- `state-aggregator`
- `mqttvirtual-mapper`
- `raw-stream-bridge`
- `docs-html`

## 기본 원칙

- Kubernetes manifest에는 `:latest` tag와 `imagePullPolicy: Always`를 사용한다.
- `docs-html`은 Argo CD Image Updater의 digest update annotation으로 새 registry digest를 감지한다.
- GitHub Actions는 docs 변경 시 `scripts/build-docs-html.py`로 `docs/html`을 먼저 재생성한 뒤 `docs-html:latest` 이미지를 build/push한다.
- Argo CD Image Updater가 Application image override를 갱신하면 Argo CD가 sync하여 새 Pod를 생성한다.
- 그 외 현재 데모 workload는 GitHub Actions가 이미지를 build/push한 뒤 workload를 rollout restart한다.

## 왜 digest pinning을 제거했는가

`image@sha256:...` 형태로 workload image가 고정되면 같은 tag에 새 이미지를 push해도 Kubernetes가 새 이미지를 사용하지 않는다.

예를 들어 아래처럼 digest가 박혀 있으면:

```text
192.168.0.56:5000/state-aggregator@sha256:...
```

새로 `192.168.0.56:5000/state-aggregator:latest`를 push해도 해당 Deployment는 기존 digest 이미지를 계속 사용한다.

따라서 현재 데모 개발/검증 단계에서는 아래 형태를 사용한다.

```text
192.168.0.56:5000/state-aggregator:latest
192.168.0.56:5000/mqttvirtual:latest
```

## GitHub Actions workflow

workflow 파일:

```text
.github/workflows/docker-build-push.yml
```

trigger:

- `main` branch push
- 관련 build context 변경 시
- 수동 실행 `workflow_dispatch`

관련 path:

```text
.github/workflows/docker-build-push.yml
.github/buildkitd.toml
edge-orch/state-aggregator/**
edge-orch/raw-stream-bridge/**
edge-orch/workflow_executor/**
edge-orch/placement_engine/**
edge-orch/vision_stage_runner/**
mappers/mqttvirtual/**
mappers/mapper-framework/**
docs/**
docs-site/**
```

현재 workflow는 다음 이미지를 build/push한다.

```text
192.168.0.56:5000/state-aggregator:latest
192.168.0.56:5000/raw-stream-bridge:latest
192.168.0.56:5000/workflow-executor:latest
192.168.0.56:5000/placement-engine:latest
192.168.0.56:5000/vision-stage-runner:latest
192.168.0.56:5000/mqttvirtual:latest
192.168.0.56:5000/docs-html:latest
```

운영 데모 경로와 문서 확인 경로에 자동 rollout하는 대상은 다음이다.

```text
deployment/state-aggregator
daemonset/raw-stream-bridge
daemonset/mqttvirtual-mapper
deployment/docs-html
```

## `docs-html`의 Image Updater 방식

`docs-html`은 정적 HTML이 이미지 안에 들어가는 구조이므로 docs 변경 시 이미지를 새로 build/push해야 한다. 다만 Pod 재시작은 GitHub Actions에서 직접 `kubectl rollout restart`하지 않고, 이미 설치된 Argo CD Image Updater가 처리한다.

`edge-orch-argocd/argocd-apps.yaml`의 `docs-html` Application에는 다음 annotation을 둔다.

```yaml
argocd-image-updater.argoproj.io/image-list: docs-html=192.168.0.56:5000/docs-html:latest
argocd-image-updater.argoproj.io/docs-html.update-strategy: digest
argocd-image-updater.argoproj.io/docs-html.force-update: "true"
argocd-image-updater.argoproj.io/write-back-method: argocd
```

흐름은 다음과 같다.

```text
1. docs 또는 docs-site 변경이 main에 push된다.
2. GitHub Actions가 `python3 scripts/build-docs-html.py`를 실행해 `docs/html`을 runner workspace에서 재생성한다.
3. GitHub Actions가 재생성된 `docs/html`을 포함해 `192.168.0.56:5000/docs-html:latest`를 build/push한다.
4. Argo CD Image Updater가 registry의 latest digest 변경을 감지한다.
5. Image Updater가 Argo CD Application override를 새 digest로 갱신한다.
6. Argo CD가 docs-html Deployment를 sync하고 새 Pod가 최신 docs 이미지를 pull한다.
```

## 자동 rollout 방식

GitHub Actions는 `state-aggregator`, `raw-stream-bridge`, `mqttvirtual-mapper`에 대해 build/push 후 다음 흐름으로 최신 이미지를 반영한다. `docs-html`은 위의 Image Updater 방식으로 반영한다.

```text
1. 현재 workload image 확인
2. image를 registry의 :latest로 설정
3. 기존 image도 이미 :latest이면 rollout restart 수행
4. rollout status로 완료 확인
```

`imagePullPolicy: Always`가 설정되어 있으므로 새 Pod가 뜰 때 registry의 최신 `:latest`를 다시 pull한다.

주의:

- registry에 tag를 push하는 것만으로 기존 Pod가 자동 재시작되지는 않는다.
- `imagePullPolicy: Always`는 새 Pod 생성 시점에만 의미가 있다.
- 그래서 GitHub Actions의 rollout restart 단계가 필요하다.

## Argo CD 역할

Argo CD Application은 다음 경로를 sync한다.

```text
edge-orch/state-aggregator/k8s
mappers/mqttvirtual/resource
docs-site
```

현재 `docs-html` Argo CD Application에는 Image Updater annotation을 둔다. 운영 데모 workload에는 아래 digest update annotation을 두지 않는다.

```yaml
argocd-image-updater.argoproj.io/image-list: ...
argocd-image-updater.argoproj.io/*.update-strategy: digest
argocd-image-updater.argoproj.io/write-back-method: argocd
```

이 annotation이 운영 데모 workload에 있으면 Argo CD Image Updater가 live Application에 digest override를 다시 넣을 수 있어, GitHub Actions rollout 방식과 충돌한다. `docs-html`은 Image Updater를 의도적으로 사용하는 예외다.

## 배포 후 확인

workflow 성공 후 클러스터에서 확인한다.

```bash
kubectl get deploy state-aggregator -n default \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}{.status.readyReplicas}{"/"}{.status.replicas}{"\n"}'

kubectl get ds mqttvirtual-mapper -n default \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}{.status.numberReady}{"/"}{.status.desiredNumberScheduled}{"\n"}'
```

정상 예:

```text
192.168.0.56:5000/state-aggregator:latest
1/1
192.168.0.56:5000/mqttvirtual:latest
2/2
```

Dashboard API 기준 확인:

```bash
kubectl exec -n default deploy/state-aggregator -- python -c '
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:8000/state/dashboard", timeout=3).read().decode()[:1000])
'
```

telemetry device는 InfluxDB latest telemetry timestamp가 fresh하면 `reason`이 다음처럼 표시된다.

```text
recent InfluxDB telemetry
```

## 운영상 주의

- 이 자동 배포는 현재 데모 운영 가시화 경로의 빠른 반영을 위한 설정이다.
- 재현성을 우선하는 배포 단계에서는 digest pinning으로 되돌릴 수 있지만, 그 경우 새 build마다 manifest 또는 Application의 digest를 갱신해야 한다.
- docs-only 변경은 `.github/workflows/docker-build-push.yml`의 path trigger에 포함되어야 한다.
- `docs-html`은 정적 파일을 이미지에 포함하므로, docs 변경 자동 반영에는 CI에서의 `docs/html` 재생성, `docs-html` 이미지 build/push, Argo CD Image Updater digest 감지가 모두 필요하다.
