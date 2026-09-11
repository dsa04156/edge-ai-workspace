# Kubeflow Hub standalone 사전 점검

- 점검일: 2026-08-31
- 대상 클러스터 context: `kubernetes-admin@kubernetes`
- Hub 검증 namespace: `kubeflow-hub-eval`
- 고정 Hub 릴리스: `v0.3.14`
- API 기준: Model Registry REST API `v1alpha3`

## 확인 결과

| 항목 | 관측 결과 | 판단 |
|---|---|---|
| Kubernetes client/server | `v1.31.14` | Hub 최소 요구사항 `1.27+` 충족 |
| Kustomize | `v5.4.2` | Hub 최소 요구사항 `5.0.3+` 충족 |
| 기본 StorageClass | `local-path` | standalone metadata DB PVC 사용 가능 |
| Cloud worker | `etri-ser0002-cgnmsb`, amd64, 24 CPU, 약 30.5GiB allocatable memory | Hub/DB 검증 workload 배치 가능 |
| 기존 `kubeflow` namespace | Kubeflow Pipelines `2.17.0`, MySQL과 20Gi PVC 운영 중 | 기존 namespace에 Hub를 중첩 설치하지 않음 |
| 기존 object store | `science-ai-mlops` namespace의 MinIO와 20Gi PVC 운영 중 | artifact smoke test에 재사용 가능, credential 값은 문서화하지 않음 |
| 기존 MLflow | `science-ai-mlops` namespace에서 운영 중 | 삭제·변경하지 않고 비교/fallback 후보로 보존 |
| KServe CRD | 설치되지 않음 | 1차 Hub qualification 범위에서 유지 |
| Edge node 상태 | 4대 중 3대 Ready, `etri-dev0003-raspi5` NotReady | Hub qualification은 cloud worker에 한정 |

## 격리 결정

공식 manifest 기본 namespace인 `kubeflow`는 이미 다른 운영 workload가 소유한다. 이번 시험은 `kubeflow-hub-eval`에만 설치하고 다음 항목은 변경하지 않는다.

- `kubeflow`의 기존 Pipelines/MySQL/PVC
- `science-ai-mlops`의 MinIO·MLflow와 credential Secret
- `edgex-system`, `edgex-edge`
- KServe CRD와 cluster-scoped storage initializer
- KubeEdge edge node의 workload

## 보안·운영 보정

- upstream manifest의 기본 DB Secret은 overlay에서 제거한다.
- `MYSQL_ALLOW_EMPTY_PASSWORD`를 제거한다.
- 설치 직전에 생성한 비밀번호를 `model-registry-db-secrets` Secret으로 주입한다.
- API와 DB Service는 `ClusterIP`로만 유지한다.
- Hub와 DB는 `environment=cloud`, `kubernetes.io/arch=amd64` node에만 배치한다.
- 이 설치는 Alpha component의 qualification이며 현재 운영 Model Registry로 선언하지 않는다.
