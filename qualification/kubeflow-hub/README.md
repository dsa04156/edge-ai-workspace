# Kubeflow Hub qualification

Kubeflow Hub Model Registry `v0.3.14`를 현재 Kubernetes/KubeEdge 클러스터에 standalone으로 격리 설치하고, metadata CRUD와 영속성을 검증한다.

## 현재 판정

**PASS WITH CONDITIONS** — 모델·버전·artifact metadata 등록/조회/수정, archive 처리, 기존 MinIO artifact 연계, Hub/DB 재시작 후 metadata 영속성을 확인했다. 다만 Alpha API, 인증 부재, node-local DB 볼륨 등 운영 전 보완 항목이 남아 있다.

상세 증거와 잔여 조건은 [results.md](results.md)에 기록한다.

## 범위

- 포함: Model Registry REST API, metadata DB, PVC, 기존 MinIO artifact URI 연계
- 제외: Full Kubeflow 추가 설치, Hub UI, Istio, KServe, Catalog, edge node 배치, 운영 트래픽

## 설치 전제

`model-registry-db-secrets`는 Git에 저장하지 않는다. namespace를 먼저 생성하고 실행 시점에 Secret을 만든 뒤 Kustomize overlay를 적용한다.

```bash
kubectl apply -f install/namespace.yaml
kubectl create secret generic model-registry-db-secrets \
  --namespace kubeflow-hub-eval \
  --from-literal=MYSQL_USER_NAME=root \
  --from-literal=MYSQL_ROOT_PASSWORD="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k install/
```

## 설치 확인

```bash
kubectl wait --for=condition=available \
  --namespace kubeflow-hub-eval \
  deployment/model-registry-db \
  deployment/model-registry-deployment \
  --timeout=180s

kubectl port-forward \
  --namespace kubeflow-hub-eval \
  service/model-registry-service 18080:8080
```

API 기준 경로:

```text
/api/model_registry/v1alpha3
```

## Smoke test

Python dependency는 검증용 가상환경에만 설치한다.

```bash
python3 -m venv /tmp/kubeflow-hub-eval-venv
/tmp/kubeflow-hub-eval-venv/bin/pip install \
  model-registry==0.3.14 onnx==1.18.0

/tmp/kubeflow-hub-eval-venv/bin/python \
  smoke/create_identity_onnx.py \
  --output artifacts/identity-v1.onnx

/tmp/kubeflow-hub-eval-venv/bin/python \
  smoke/register_model.py \
  --artifact artifacts/identity-v1.onnx \
  --artifact-uri \
  s3://edge-ai-models/qualification/identity/0.1.0/model.onnx
```

`register_model.py`는 같은 모델을 다시 만들지 않는 idempotent smoke test다. 모델·버전·artifact와 Edge metadata를 재조회하고, 모델 설명 수정이 유지되는지 함께 검사한다. MinIO bucket 생성과 object 업로드는 클러스터별 credential 처리 방식이 다르므로 스크립트에서 자동화하지 않는다.

## 제거

검증 namespace 전체가 명시적 삭제 대상이다. 기존 `kubeflow`, `science-ai-mlops`, EdgeX namespace는 제거 대상이 아니다.

```bash
kubectl delete namespace kubeflow-hub-eval
```

실제 삭제는 qualification 결과 보존 여부를 확인한 뒤 별도 승인하에 수행한다.
