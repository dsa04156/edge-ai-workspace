# Kubeflow Hub standalone qualification 결과

- 검증일: 2026-08-31
- 대상: Kubeflow Hub Model Registry `v0.3.14`, REST API `v1alpha3`
- namespace: `kubeflow-hub-eval`
- 판정: **PASS WITH CONDITIONS**

## 결론

현재 Kubernetes `v1.31.14` 클러스터에서 Kubeflow Hub를 standalone Model Registry로 사용할 수 있다. 모델 artifact는 기존 MinIO에 두고 Hub에는 모델·버전·artifact URI와 Edge 배치용 metadata를 저장하는 기본 흐름이 동작했다.

따라서 다음 구현 단계에서는 Full Kubeflow나 KServe를 먼저 추가하지 않고, 이 Registry 계약 위에 `EdgeAILibrary SDK -> Profiler -> Profile Aggregator`를 붙인다. 이 결과는 Hub의 운영 승인이나 KServe 도입 승인을 의미하지 않는다.

## 검증 결과

| 검증 항목 | 관측 증거 | 결과 |
|---|---|---|
| 격리 설치 | 기존 `kubeflow`, `science-ai-mlops`를 변경하지 않고 `kubeflow-hub-eval`에 설치 | PASS |
| Hub/DB 가용성 | `model-registry-deployment`, `model-registry-db` 모두 `1/1 Available` | PASS |
| DB 영속 볼륨 | `metadata-mysql` PVC `Bound`, 2Gi, `local-path`, volume `pvc-806da4ee-abd5-458a-a31c-1c0e65bccfc2` | PASS |
| Create/Read | 모델 `edge-ai-identity-smoke` ID `1`, 버전 `0.1.0` ID `2`, artifact ID `1` 생성 후 조회 | PASS |
| Update | 모델 설명을 변경하고 재조회하여 값 유지 확인 | PASS |
| Delete 의미 | REST API에 hard delete가 없어 별도 모델 ID `3`을 `ARCHIVED`로 전환하고 재조회 | PASS WITH LIMITATION |
| Edge metadata | `architectures`, `runtimeCandidates`, `profileRef`, artifact SHA-256, qualification flag 일치 확인 | PASS |
| MinIO 연계 | `s3://edge-ai-models/qualification/identity/0.1.0/model.onnx` 업로드·조회 | PASS |
| Artifact 무결성 | 로컬과 MinIO object SHA-256 모두 `4934e04da891314e4430060e545f7cc8289165b7c0641dda5d51a68450779966` | PASS |
| 재시작 영속성 | DB와 Hub를 순차 재시작한 뒤 동일한 모델/버전/artifact ID와 metadata 재조회 | PASS |

재시작 후 조회 결과의 핵심 값은 다음과 같다.

```json
{
  "created": false,
  "model": {"id": "1", "name": "edge-ai-identity-smoke"},
  "version": {"id": "2", "name": "0.1.0"},
  "artifact": {
    "id": "1",
    "format": "onnx",
    "uri": "s3://edge-ai-models/qualification/identity/0.1.0/model.onnx",
    "sha256": "4934e04da891314e4430060e545f7cc8289165b7c0641dda5d51a68450779966"
  },
  "metadataVerified": true,
  "updateVerified": true
}
```

archive 검증 모델은 재조회 시 `state: ARCHIVED`였다.

## 운영 전 필수 조건

1. **인증·인가 경계**: standalone API는 현재 `ClusterIP`지만 access token 없이 호출된다. 외부 노출 전에 인증 프록시 또는 service mesh 정책, NetworkPolicy, 호출 주체별 권한 모델을 정해야 한다.
2. **Alpha API 수용 여부**: Hub `v0.3.14`와 REST `v1alpha3`는 Alpha 단계다. SDK 내부에 Registry Adapter를 두어 API 변경 영향을 격리해야 한다.
3. **DB 가용성과 백업**: 현재 `local-path` RWO PVC는 단일 node 장애에 취약하다. 운영 전 CSI 기반 StorageClass, 정기 백업, 실제 restore 시험이 필요하다.
4. **초기 기동 순서**: 첫 설치 시 DB image pull과 초기화가 늦어 API pod가 한 번 재시작했다. 운영 overlay에는 DB 연결 대기 initContainer 또는 충분한 startup probe를 추가한다.
5. **스케줄링**: selector가 `environment=cloud`, `amd64`만 제한해 실제 pod는 control-plane node `etri-ser0001-cg0msb`에 배치됐다. 운영 시 전용 cloud worker label과 리소스 정책으로 좁혀야 한다.
6. **삭제 정책**: 현재 API의 삭제 의미는 hard delete가 아니라 archive다. 보존 기간, artifact garbage collection, MinIO object 삭제 책임을 별도로 정의해야 한다.
7. **KServe 분리**: 이 검증에는 KServe가 포함되지 않았다. 현 Kubernetes `v1.31.14`에서 최신 KServe를 억지로 추가하지 않는다.

## 다음 작업 순서

1. Hub API를 직접 퍼뜨리지 않도록 `Registry Adapter` 인터페이스를 정의한다.
2. `EdgeAILibrary SDK`가 모델과 runtime 후보를 등록하고 profile 요청을 만드는 최소 계약을 구현한다.
3. ONNX Runtime CPU 한 종류로 Profiler를 구현해 latency, memory, throughput 결과를 Hub metadata 또는 별도 Profile Store에 연결한다.
4. 두 실행환경의 profile이 확보된 뒤에만 Placement Engine의 정적 규칙부터 구현한다.
5. KServe와 동적 offloading은 위 흐름이 검증된 이후 별도 단계로 평가한다.

## 범위 밖이거나 미완료인 항목

- Full Kubeflow, Hub UI, Catalog 검증
- KServe `InferenceService`
- DB backup/restore 실제 복구 시험
- 다중 replica/HA와 장애 node failover
- 실제 Raspberry Pi/Jetson runtime profiling
- 동적 재배치와 offloading
