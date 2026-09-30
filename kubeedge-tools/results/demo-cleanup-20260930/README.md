# 시험·AI 데모 워크로드 정리 — 2026-09-30

사용자의 Llama·센서 anomaly 등 불필요한 시험 서비스 정리 요청에 따른 운영 변경이다.
실행·접속 리소스를 제거했으며 Namespace·PVC·설정·소스·모델 캐시·기존 시험 근거는 보존했다.

## 제거 대상과 결과

| 구분 | 제거한 대상 |
|---|---|
| 공통 runtime | RuntimeService `llama-inference`, `digits-classifier`, `quality-api-demo`, `telemetry-transform-demo`; 소유 배포 revision 18개와 Service 18개 |
| Llama | `llama-continuity-test`의 Nano/AGX/Spark worker, 중지된 continuity/ordered controller: Deployment 5개·Service 4개 |
| 센서 anomaly | `edgex-edge` 본체·server1, `edge-ai-workloads` 전환 시험체 2개: Deployment 4개·Service 2개 |
| 기타 데모 | edgex-ai-input, mobilint-core-demo, vd-demo-001, edge-modbus-simulator: Deployment 4개·Service 3개 |
| 전용 제어·접속 | 센서 anomaly Argo Application 1개·server1 AugmentationResource 1개·NetworkPolicy 4개 |
| 잔여 시험 Pod | 완료된 node-debugger 4개; 삭제한 배포 소유의 실패·종료 Pod는 GC로 정리 |

합계 Deployment 31개·Service 27개·RuntimeService 4개 제거.
이전 스냅샷의 대상 Pod 38개가 최종 조회에서 모두 없어졌다. 이 값은 작업 중 생성·종료된
모든 Pod의 누적 수나 38개 실행 중 Pod를 뜻하지 않는다. 삭제한 Service의 Endpoints 27개도 제거됐다.

## 절차와 예외

1. 운영 workload·Pod·서비스·PVC·Argo·runtime·설정·관련 권한 원본을 비공개 경로에 백업했다.
2. 전용 AI 입력기 제거 후 RuntimeService를 삭제해 기존 Operator의 drain/finalizer 처리를 사용했다.
3. 센서 anomaly Application은 상위 ApplicationSet/owner와 finalizer가 없음을 확인하고 orphan 삭제했다.
   PVC까지 지우는 Argo cascade 삭제나 namespace 전체 삭제는 사용하지 않았다.
4. Llama의 runtime 정의 삭제 완료 후 resident worker와 옛 controller, 독립 데모 Deployment·Service를 제거했다.
5. quality-api-demo는 Operator의 Service `/ready` 조회가 timeout이었지만 worker 내부에서는
   `ready=true`, `inFlight=0`이었다. 신규 runtime 요청 경로가 닫힌 상태에서 해당 배포만 scale 0으로
   정상 종료했고, 이후 Operator가 finalizer를 정리했다. 강제 Pod 삭제·finalizer 제거는 하지 않았다.
   네트워크 timeout의 하위 원인은 이번 정리에서 확정하지 않았다.
6. 재조회로 대상 없음과 보존 대상을 확인했다. 새 추론·반복 부하·장비 스트레스는 실행하지 않았다.

최초 Argo 삭제 명령의 짧은 resource명 `application`은 다른 API group으로 해석되어 NotFound였다.
아무 Application도 변경되지 않았고 `applications.argoproj.io`로 정확히 지정해 삭제했다.

## 검증과 보존

- [운영 전후 비교](verification.json): 제거 객체의 종류·namespace·이름, 비대상 spec 비교와 PVC 보존 결과.
- [API 확인](api-checks.jsonl): 대시보드·디바이스·runtime API HTTP 200, runtime services 0개·관측 오류 없음.
- 비대상 workload spec 변경 0개. PVC 30개 모두 같은 UID와 phase다.
- EdgeX core·Serial·Sense HAT·Runtime Operator·state-aggregator·확인한 장비 plugin Pod의 UID·Ready를 유지했다.
  일부 discovery/EdgeMesh Pod의 ready/restart 차이는 verification.json에 보존하며 원인을 단정하지 않는다.
- 최근 재설치된 AgentOps·Kubeflow 등 다른 스택은 이번 AI 서비스 데모 정리에 포함하지 않았다.
  device-augmentation-controller 등 관리 구성요소도 유지했다.
- raw runtime 원장에는 Deleted 서비스 이력이 남을 수 있다. 대시보드 runtime 목록은 0개다.
  Git 서비스 catalog·독립 시험 설정은 보존 자료이며 실행 자원이 존재한다는 뜻이 아니다.

## 재생성 방지와 복구

운영 센서 anomaly Application은 제거됐다. 로컬 `edge-orch-argocd/sensor-anomaly-demo-app.yaml`은
`edge-ai.io/lifecycle: retired`와 자동 동기화 제거로 정렬했다. 원격 Git 반영은 아직 하지 않았다.
보존 manifest·catalog를 수동 apply/sync하면 다시 실행될 수 있으므로 별도 재실행 요청 없이 적용하지 않는다.

원본 정의·작업 로그·전후 스냅샷 위치:
`/home/jinuk/.local/state/codex/demo-cleanup-20260930/` (상위 디렉터리 0700).
설정 값을 포함한 전체 백업은 Git에 추가하지 않는다.

복구 요청 시 백업에서 필요한 객체만 선택한다. 기존 PVC UID를 확인하고 UID/resourceVersion/status 등
서버 생성 metadata를 제외한 선언을 준비한다. RuntimeService는 우선 suspended 상태로 등록하고,
실제 재개·Llama resident 연결·센서 입력기는 요청된 시험 범위에 맞춰 순차 복구한다.
모든 namespace의 백업을 통째로 apply하거나 시험 부하를 자동 재실행하지 않는다.

현재 운영 정리는 반영 완료다. 소스·문서 변경은 로컬이며 커밋·push·새 이미지 배포는 수행하지 않았다.
