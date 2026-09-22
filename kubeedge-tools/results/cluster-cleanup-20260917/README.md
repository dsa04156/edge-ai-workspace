# 미사용 AI 스택·실험 워크로드 정리

확인일: 2026-09-17. 대상 context: `kubernetes-admin@kubernetes`.
사용자가 미사용 Pod·Service 정리를 요청했고 Kueue를 명시적으로 확인했다.
현재 EdgeX·runtime-operator·NEXUS·KubeEdge·관측 기반은 유지했다.

## 실제 조치

| Namespace | Deployment 제거 | Service 제거 | 보존 PVC |
|---|---:|---:|---:|
| ai-scientist | 1 | 1 | 3 / 45Gi |
| kubeflow | 12 | 7 | 1 / 20Gi |
| kubeflow-hub-eval | 2 | 2 | 1 / 2Gi |
| kueue-system | 1 | 3 | 0 |

Ingress 4개, AI Scientist failed-pod-gc CronJob 1개도 제거했다.
Pod는 정리 전 19개(Running 16개)에서 0개로 줄었다. Deployment 소유 ReplicaSet도 0개다.
PVC·PV·Namespace·ConfigMap·Secret과 namespaced RBAC는 유지했다.
67Gi는 PVC 선언 용량이며 디스크 회수량이 아니다. 컨테이너 이미지와 볼륨 데이터를 삭제하지 않았다.

대상 배포를 관리하는 Argo CD Application·Helm release와 HPA는 없었다.
Argo Workflow·CronWorkflow·Kubeflow ScheduledWorkflow도 0개였다.
Kueue Workload 0개와 Kueue label이 붙은 Pod·Deployment·StatefulSet·Job·CronJob 0개를 확인했다.

Kueue는 controller를 먼저 중지하지 않았다. LocalQueue 1개, ClusterQueue 1개,
ResourceFlavor 1개, WorkloadPriorityClass 3개를 백업하고 삭제했으며 controller가
resource-in-use finalizer를 정상 처리하도록 기다렸다. 이후 admission webhook 2개,
Kueue CRD 11개, visibility APIService 2개, Deployment·Service와 controller 전용
ClusterRoleBinding 2개를 제거했다. finalizer 강제 제거는 하지 않았다.
API conversion이 중지된 webhook으로 향하는 CRD를 남기지 않았다.
공식 제거 범위 참고: [Kueue 설치·제거 문서](https://kueue.sigs.k8s.io/docs/getting-started/installation/).
실행은 최신 원격 manifest를 일괄 삭제하지 않고 실제 설치 객체를 지정했다.

Kubeflow cache-deployer를 정지·제거하고 `cache-webhook-kubeflow`를 제거했다.
`science-ai-system/mini-science-ai-os-alerts`의 `ScienceKueueWorkloadLongPending`과
`ScienceKubeflowUnavailable` 두 경보만 제거했다. 나머지 경보는 유지했다.

## 검증과 한계

- 대상 네임스페이스의 Deployment·StatefulSet·DaemonSet·Pod·ReplicaSet·Service·Ingress·CronJob·Job 0개.
- 기존 PVC 5개의 UID·Bound 상태 유지. 설정과 Secret 유지.
- 대상 webhook 0개, Kueue CRD 0개. Pod 생성 `--dry-run=server` 성공; 실제 Pod 생성 없음.
- 비대상 Deployment·StatefulSet·DaemonSet의 spec 동일, 비대상 Pod UID 동일.
- NEXUS `/`, `/state/runtime-services`, `/state/devices` HTTP 200.
  runtime 서비스 4개·device 항목 13개 조회. 추론 응답·sensor freshness 전체 검증과 구분한다.
- 삭제 전부터 재시작하던 NVIDIA device plugin의 restart count 933→934와 Ready 전환,
  `sensor-anomaly-inference-server1`의 Pending→Running을 관측했다. 해당 workload를 직접
  변경하지 않았으며 성능 개선·근본 원인 해결로 주장하지 않는다.
- 처음 시도한 `/health`는 존재하지 않아 404였고, 실제 공개 경로로 위 검증을 수행했다.
- 첫 정리에서 MLflow·MinIO·과학 AI 허브·tenant API와 다른 실험 namespace는 유지했다.
  MLflow는 아래 후속 요청으로 추가 정리했다.
  `tenant-etri/science-job-api`의 `KFP_ENDPOINT`가 제거된 Kubeflow를 참조한다.
  해당 파이프라인 실행 기능은 중단된 상태이며 별도 과학 AI 스택을 계속 사용할 경우 재설정이 필요하다.

## 후속 MLflow 정리

사용자의 추가 요청으로 2026-09-17 `science-ai-mlops/mlflow` Deployment·Service·Ingress
각 1개를 제거했다. 소유 ReplicaSet과 Pod 2개(Running 1개, 종료 상태 1개)도 사라졌다.
앞선 정리와 합계 Deployment 17개·Service 14개·Ingress 5개, 제거한 Running Pod는 17개다.

MLflow Deployment의 데이터 경로는 `mlflow-data` PVC였다. 선언 용량 5Gi의 PVC는
동일 UID·Bound 상태로 보존했고, 나머지 설정과 Secret도 유지했다. MinIO StatefulSet·Service와
데이터는 변경하지 않았으며 `minio-0`의 동일 UID·Ready 상태를 확인했다.
검증 완료 시 MLflow Deployment·ReplicaSet·Pod·Service·Ingress는 0개였다.
MLflow를 참조하는 다른 Deployment·StatefulSet·CronJob 명세나 전용 모니터링 객체는 조회에서
발견하지 못했다. 애플리케이션 내부 코드와 외부 클라이언트 전체를 검사했다는 뜻은 아니다.

원본 정의·조치·검증은 아래 비공개 백업 경로의 `mlflow/` 하위 `before.json`, `actions.json`,
`after.json`, `verification.json`에 추가했다. 실행 리소스 삭제이며 실험 데이터 영구 삭제가 아니다.

## 후속 과학 AI 스택·과거 실험 정리

사용자가 남은 후보를 확인하고 추가 정리를 승인했다. 2026-09-17 실행 시점에 원본 정의를
다시 백업하고 Helm·Argo CD·HPA 소유권, 현재 RuntimeService와 외부 Deployment·StatefulSet·
DaemonSet·ConfigMap·접속 경로의 참조를 확인했다. 아래 대상의 자동 재생성 관리 주체는
발견하지 못했으며 대상에는 활성 HPA·CronJob이 없었다.

| Namespace | Deployment | StatefulSet | Service | Ingress | Pod / Running |
|---|---:|---:|---:|---:|---:|
| science-ai-system | 4 | 0 | 5 | 4 | 6 / 6 |
| tenant-etri | 2 | 0 | 2 | 2 | 6 / 4 |
| science-ai-mlops — MinIO | 0 | 1 | 1 | 0 | 1 / 1 |
| ai-placement-experiment | 7 | 0 | 0 | 0 | 2 / 2 |
| offload-test | 7 | 0 | 7 | 0 | 7 / 6 |
| llama-offload-eval | 5 | 0 | 1 | 1 | 5 / 3 |
| codex-work | 1 | 0 | 2 | 3 | 2 / 1 |
| 합계 | 26 | 1 | 18 | 10 | 29 / 23 |

추가로 `offload-test`의 종료 Job 2개, 대상 전용 PrometheusRule 1개·ServiceMonitor 3개를
제거했다. 소유 ReplicaSet 160개도 정리됐다. 시스템 공통 Prometheus와 경보는 유지했다.
MinIO StatefulSet의 `whenDeleted`·`whenScaled`가 모두 `Retain`임을 확인한 뒤 삭제했다.
대상 네임스페이스를 삭제하지 않아 설정·Secret·RBAC·PVC를 보존했다.

추가 범위 PVC 6개는 동일 UID와 상태를 유지했다. `science-ai-mlops`의 MinIO 20Gi·
과거 Postgres 10Gi·MLflow 5Gi, `llama-offload-eval`의 Spark cache 4Gi·demo records 1Gi는
Bound이고 AGX cache 4Gi는 원래 Pending이다. PVC 선언 용량과 실제 저장·회수량을 구분한다.
Codex 대시보드가 hostPath로 읽던 작업공간·설정·소스 파일도 삭제하지 않았다.

현재 `llama-inference`는 `llama-continuity-test`의 Nano·AGX·Spark worker와 Service만
참조하므로 해당 배포·볼륨은 유지했다. 옛 `llama-offload-eval`을 참조하는 ConfigMap은
replicas 0인 `ordered-offload-controller`에만 연결되어 있었다. 이 과거 controller 정의를
다시 기동하려면 제거된 의존 관계를 먼저 재검토해야 한다. 현재 공통 operator와 함께 기동하지 않는다.

검증 시각 2026-09-17 19:49 KST 기준:

- 7개 대상의 Deployment·StatefulSet·DaemonSet·ReplicaSet·Pod·Service·Ingress·CronJob·Job 0개.
- 비대상 배포 spec와 Pod UID·phase·container ready/restart 값 변경 0건.
- NEXUS `/`·`/state/runtime-services`·`/state/devices` HTTP 200.
  runtime 4개, 관측 오류 없음, snapshot age 약 2.3초; device 항목 13개.
- 실제 추론·반복 부하·장애 주입은 수행하지 않았다. API 조회 성공을 전체 추론·telemetry
  정상으로 확대하지 않는다. 기존 AGX worker 준비 미완료 등은 이번 정리로 해결한 항목이 아니다.

전체 단계 합계: Deployment 43개·StatefulSet 1개·Service 32개·Ingress 15개,
CronJob 1개·Job 2개·Pod 50개(Running 40개) 제거. 과제의 EdgeX·NEXUS·runtime,
현재 Llama worker, 모빌인트·가상 디바이스 검증과 공통 운영 기반은 유지했다.
빈 namespace·기존 PVC·설정이 보이는 것은 데이터와 복구 정의를 보존했기 때문이다.

추가 원본·조치·검증은 아래 비공개 경로의 `remaining/` 하위 `*-before.json`,
`actions.json`, `verification.json`, `http-verification.json`에 보관했다.

## 백업·복구

원본 정의와 조회 원장은 `/home/jinuk/.local/state/codex/cluster-cleanup-20260917/`에 있다.
디렉터리 0700·파일 0600으로 제한했으며 Secret이 포함된 원본을 저장소에 복사하지 않았다.
주요 파일은 `*-before.json`, `kueue-all-objects-before.json`, `actions-core.json`,
`actions-kueue.json`, `verification-summary.json`, `http-verification.json`이다.
이는 Kubernetes 정의 백업이며 데이터베이스 dump나 볼륨 백업은 아니다. 데이터는 기존 PVC에 남아 있다.

복구 시 원본 UID·resourceVersion·status·managedFields를 제거한 필요한 선언만 사용한다.
Kueue는 CRD·RBAC·기존 설정·controller·Service를 복구하고 webhook 준비를 확인한 뒤
admission/APIService와 ResourceFlavor→ClusterQueue→LocalQueue 순으로 복원한다.
Kubeflow·AI Scientist는 보존한 PVC·설정·Secret을 사용해 Deployment·Service·Ingress를
복원한다. 원본 List 전체를 무검토로 apply하거나 namespace를 삭제하지 않는다.

실클러스터 정리 완료. 기록·문서 생성물은 로컬 미커밋이며 문서 웹 배포는 하지 않았다.
