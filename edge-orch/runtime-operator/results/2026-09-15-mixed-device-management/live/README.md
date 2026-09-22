# 혼합 디바이스 운영 배포·실클러스터 검증

> **2026-09-16 운영 복원:** 사용자 요청으로 9월15일 혼합100개/논리 가상 디바이스 확장 배포를 철회하고
> 대시보드·runtime-operator를 그 직전 이미지로 되돌렸다. 신규 관리 API·화면은 운영에서 비활성이다.
> 아래 확장 내용은 보존한 로컬 구현·시험 이력이며 현재 운영 기능이 아니다.
> 시험 RuntimeService5개는 제거했고 기존4개 서비스 설정은 보존했다. 정의88개와 이력은 백업·PVC에 보존한다.

검증일: 2026-09-15. 최초 로컬 검증 뒤 사용자 진행 승인으로 엔진·대시보드 배포와 지정 시험을 수행했다.
**100개 관리 기능은 아래 산정 조건에서 확인했다. 병렬 실행은 재시험을 통과했지만 첫 시험의 간헐503 원인은 미해결이다. 공식 연차 목표 달성이나 장기 안정성 완료로 선언하지 않는다.**

## 쉽게 설명하면

등록 카드88장을 추가하고 기존 센서 등록 항목12개와 함께 관리했다. 등록만 할 때는 Pod가 생기지 않았다.
그중4개를 실행하면 Pod4개가 생기고, 하나를 껐다 켜도 등록 카드는 같고 Pod만 바뀐다.
시험이 끝난 지금88개 카드는 정지 상태로 남았고 시험 Pod는0개다.

## 배포와 재시작

- 단일 엔진: `platform-runtime/runtime-operator`, replicas1, Recreate, 기존 `runtime-journal` PVC,
  `/data/runtime.sqlite3`, `etri-ser0001-cg0msb`에 고정. 시작 전 같은 PVC에 SQLite backup을 생성했다.
- 운영자는 기존 수동 설치 경로로 엔진 이미지·논리 관리 flag와 RuntimeService create 권한을 반영했다.
- 대시보드는 기존 Argo CD `edge-orch-state-aggregator`의 이미지·flag override로 배포했다. Synced/Healthy를 확인했다.
- 로컬 Docker socket 사용 불가로 기존 불변 운영 이미지를 base로 사용하는 OCI source layer를 생성했다.
  의존 패키지는 교체하지 않았다. 실행 중인 소스22개(엔진4/대시보드18)의 SHA256을 대조했다.
- runtime-operator image: `192.168.0.56:5000/runtime-operator@sha256:eae070c4dadd2167449cba4ffc7f93feac3e439f0cea00da0646b248b5b74756`.
- state-aggregator image: `192.168.0.56:5000/state-aggregator@sha256:93dbe63bd8e957470ac2b75f5b761713c3ed98473cdd171c883756db7f65fa26`.
- 정확한 imageID·소스 SHA·배포 상태는 [deployment.json](deployment.json)이 권위다.
  코드·manifest는 로컬 미커밋이며 Git 전체 push나 기존 AI 서비스 재배포는 수행하지 않았다.
- 엔진을 같은 노드에서 rollout restart한 뒤88개 UUID·프로파일·연결·revision·이력을 모두 확인했다.
  [engine-restart.json](engine-restart.json), [persistence.json](persistence.json).

## 1. 관리 가능 수 시험

| 항목 | 실제 결과 |
|---|---|
| 지정 시험 집합 | 실제 EdgeX 기능 endpoint12개 + 논리 가상88개 =100개 |
| 가상 개별 작업 |88개 각각 등록, 동일 등록 재요청의 UUID 일치, 연결 설정, 정지 접수, 상태·이력 조회 |
| 물리 개별 작업 |기존 EdgeX 관리 API로12개 description 변경→Core Metadata readback→원래 description 복원 |
| 물리 보존 |12개 모두 adminState·protocols 보존, 센서 command/actuator 호출 없음 |
| 등록 시 자원 |RuntimeService 추가0 / Pod 추가0 |
| 영속성 |엔진 재시작 후88개 정의와 이력 보존 |
| 정지 포함 |포함. 미할당 가상88개는 원장에 근거한 stopped |
| 조회용 표현 |관측 트윈·physical-vd·서비스 정의·실행 Pod 추가 집계 없음 |

[cohort.json](cohort.json), [physical-control.json](physical-control.json),
[inventory-registered.json](inventory-registered.json)에 개별 결과를 보관한다.
EdgeX 기능 endpoint12개는 물리 섀시12대가 아니다. 기능별 분리를 요청한 화면 단위를 사용한다.
기존12개 물리 항목의 등록 존재·조회·안전한 개별 설정은 확인했지만, 운영 센서를 새로12개 등록하거나
전원·실행 상태를 제어한 시험은 아니다. 컴퓨팅 노드10개는 전체 목록에 포함되지만 이100개 제어 집합에서는 제외했다.

## 2. 실제 Pod 병렬 실행과 자원 제한

CPU 프로파일: 요청100m/64Mi, 제한250m/128Mi. 서로 다른 논리 객체002~005와 RuntimeService UID4개를 실행했다.
동일 엔진 노드에서 실제 Pod UID4개를 확인했다. 컨테이너의 `cpu.max=25000 100000`,
`memory.max=134217728`을 읽어 자원 제한이 적용됐음을 검증했다.

| 회차 | 결과 | 판정 |
|---|---|---|
| 최초 병렬 |동시4개×5라운드20요청, 성공17 /503 3 |실패 |
| 진단 재시험 |20요청 성공, 한 객체 정지 후 나머지3개 응답, 재시작 객체1개 응답: 합계24/24 |해당 기능 시험 통과 |
| 정리 |4개 모두 stopped, 시험 Pod0개 |확인 |

첫503은 `route_unavailable`이며 dispatch 전 거절이다. 원장과 요청 diagnostics에서20건 전체를 대조했다.
첫 응답 성공시간도 약0.8~5.1초로 입력의 합성 지연150ms보다 길었다. 당시 serving/checkedAt/snapshot의
어느 조건이 깨졌는지 순간 상태를 확보하지 못해 하위 원인을 확정할 수 없다.
재시험은 실패 응답과 엔진 순간 상태를 남기도록 시험 스크립트만 보강했다. **운영 제어기를 고치거나
15초 freshness 조건을 완화하지 않았으며, 재시험 성공을 최초 오류 해결로 해석하지 않는다.**

[최초 diagnostics](parallel-first-attempt-diagnostics.json), [최초 dispatch 원장](parallel-first-attempt-requests.json),
[최초 실행 증거](attempt-1/parallel-pods.json), [재시험 요청별 결과](parallel-attempts.json),
[재시험 Pod/cgroup](parallel-pods.json), [재시험 최종 결과](parallel-result.json).

한 개 정지/재시작 중 다른3개를 유지했고 재시작 객체의 논리 UUID·RuntimeService UID는 같으며 Pod UID는 바뀌었다.
이는 관리상 정지 격리 시험이다. 강제 Pod 장애·노드 장애·장기 부하·100개 동시 실행 시험은 아니다.
실행 이미지는 기존 불변 `runtime-contract-demo`의 합성 HTTP echo이며 실제 AI 모델 성능으로 부르지 않는다.

## 3. GPU 할당 시험

객체001은 위 CPU/메모리 사양에 `nvidia.com/gpu` 요청/제한1개를 추가했다.
실제 Pod의 자원 선언, cgroup, 컨테이너 내부 `/dev/nvidia0` 존재와 HTTP5/5응답을 확인했다.
시험 후 stopped, 해당 Pod0개다. [GPU 자원 증거](gpu-pods.json), [GPU 결과](gpu-result.json).
**GPU 장치 할당·노출 시험이며 CUDA 연산, 모델 GPU 메모리 사용·처리량·성능을 검증하지 않았다.**

## 최종 상태와 기존 기능 보존

- 전체 목록112 = 노드10 + EdgeX13 + 기존 독립 가상1 + 새 논리 가상88.
- 최종 등록112 / 상태조회가능112 / 동작·실행21 / 정지89 / 확인불가0 / 기타2.
  기타2는 기존 DOWN EdgeX endpoint와 NotReady 노드다. 관측된 사용 불가를 정지로 바꾸지 않는다.
- 새 가상88개 모두 정지, 시험 Pod0개. 실행했던5개 RuntimeService 정의는 suspended로 남는다.
- 기존4개 RuntimeService의 UID와 전체 spec이 배포 전과 같다.
  quality-api-demo·telemetry-transform-demo는 Serving, digits-classifier·llama-inference는 기존 Suspended다.
- [최종 목록](inventory-final.json), [기존 서비스 보존·정리](preservation-final.json).
- 실제 운영 브라우저에서112개와5개 수치, 검색/선택/이력,1440px·390px 고정 높이 목록을 확인했다.
  이미지: 저장소 `output/playwright/mixed100-live-desktop.png`, `mixed100-live-mobile.png`.
- 물리 설정 시험 중 Core Data의 일시적503/HandlerTimeout이 관측됐고 이후12개 센서 조회가 회복됐다.
  EdgeX 장애를 새 논리 관리가 발생시켰다고 확정할 근거는 없다. 이번 시험에서 EdgeX 설정·배포를 바꾸지 않았다.

## 자동시험과 남은 조건

이 변경 기준 runtime 전체152, aggregator 전체443, JavaScript314, 문서14개 통과 근거가 있다.
운영 flag·manifest 반영 후 관련 runtime8개를 다시 통과했다. 전체 저장소114개 통과/기존2개 실패
(추진계획 줄 수 상한, 기존 Argo branch 기대값)은 최초 기록과 동일 범위다.

남은 조건은 간헐 gateway503 원인·재현과 안정성 시험, EdgeX 일시 timeout 원인,
강제 장애 격리·장기 부하, 공식100개 산정 단위 및 정지 포함 조건 승인이다.
100개 등록 수나 재시험 한 번의 성공만으로 목표 전체 달성을 선언하지 않는다.
관련 문서 HTML은 로컬 재생성했으며 문서 웹의 새 배포는 수행하지 않았다.

## 재현 범위

시험 도구는 상위 [verify_live.py](../verify_live.py)다. `--execute`가 필수이며 지정 `qa-mixed100-*` 객체만 실행한다.
`register`는 최초 등록용으로 다시 실행하지 않는다. `persistence`는 직전 등록 snapshot 기준 보존 시험이다.
`parallel`은002~005, `gpu`는001을 실행하고 정지한다. 운영 상태를 바꾸므로 해당 작업의 승인 범위에서 실행한다.
실패 회차를 덮어쓰지 않도록 별도 output 디렉터리를 지정한다.
