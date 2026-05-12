# CI/CD 자동 배포 기준

## 목적

이 문서는 현재 KubeEdge 혼합 디바이스 edge AI 운영 가시화 PoC에서 GitHub Actions와 Argo CD를 함께 사용해 새 이미지를 자동 반영하는 기준을 정리한다.

현재 자동 배포 대상은 운영 데모 경로에 직접 필요한 두 구성 요소다.

- `state-aggregator`
- `mqttvirtual-mapper`

## 기본 원칙

- Kubernetes manifest에는 `:latest` tag와 `imagePullPolicy: Always`를 사용한다.
- Argo CD Application에는 image updater의 digest pinning annotation을 두지 않는다.
- GitHub Actions가 이미지를 build/push한 뒤 workload를 rollout restart한다.
- Argo CD는 Git에 선언된 기본 desired state를 유지하고, GitHub Actions는 새 이미지 tag를 실행 중 Pod에 pull시키는 역할을 맡는다.

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
edge-orch/workflow_executor/**
edge-orch/placement_engine/**
edge-orch/vision_stage_runner/**
mappers/mqttvirtual/**
mappers/mapper-framework/**
```

현재 workflow는 다음 이미지를 build/push한다.

```text
192.168.0.56:5000/state-aggregator:latest
192.168.0.56:5000/workflow-executor:latest
192.168.0.56:5000/placement-engine:latest
192.168.0.56:5000/vision-stage-runner:latest
192.168.0.56:5000/mqttvirtual:latest
```

운영 데모 경로에 자동 rollout하는 대상은 다음이다.

```text
deployment/state-aggregator
daemonset/mqttvirtual-mapper
```

## 자동 rollout 방식

GitHub Actions는 build/push 후 다음 흐름으로 최신 이미지를 반영한다.

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
```

현재 Argo CD Application에는 아래 digest update annotation을 두지 않는다.

```yaml
argocd-image-updater.argoproj.io/image-list: ...
argocd-image-updater.argoproj.io/*.update-strategy: digest
argocd-image-updater.argoproj.io/write-back-method: argocd
```

이 annotation이 있으면 Argo CD Image Updater가 live Application에 digest override를 다시 넣을 수 있어, `:latest` 기반 자동 rollout과 충돌한다.

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
- docs-only 변경은 image build path에 포함되지 않으면 workflow를 트리거하지 않는다.
