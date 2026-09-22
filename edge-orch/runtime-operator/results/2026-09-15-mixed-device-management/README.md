# 혼합 디바이스 100개 관리와 병렬 실행 로컬 검증

아래는 최초 로컬 검증 기록이다. 후속 승인으로 수행한 운영 배포·실제 Pod 검증은 [운영 검증](live/README.md)을 우선한다.

최초 검증일: 2026-09-15. 이 로컬 시험에서는 운영 클러스터 변경 없음. 실제 결과: [verification.json](verification.json).
[설계·API·산정 기준](../../../../docs/서비스형-가상-디바이스-설계.md)을 따른다.

## 시험을 분리한 이유

100개 등록·조회·개별 제어와 다중 실행체의 실제 병렬 실행은 다른 능력이다.
정지 논리 객체도 관리 대상에 포함하지만 등록 개수만으로 목표 달성을 선언하지 않는다.
이 결과는 단일 호스트 로컬 기능 검증이다. 단일 Kubernetes 노드 배포 인수 결과는 아니다.

## 1. 혼합 100개 관리

| 항목 | 실제 확인 결과 |
|---|---|
| 구성 | 모의 EdgeX 등록 endpoint 1개 + 영속 가상 객체 99개 |
| 엔진 | 프로세스1개·SQLite writer1개, 실제 FastAPI aggregator proxy→runtime owner |
| 물리 경로 | 기존 DeviceManagementService 등록 saga·readback, LOCKED→UNLOCKED→LOCKED 3회 |
| 가상 경로 | 99개 각각 등록·동일 요청 재등록·조회·연결 변경·정지·동일 제어 재요청·이력 조회 |
| 재시작 | 99개 UUID·프로파일·연결·이력·정지 상태 보존 |
| 정상 집계 | 등록100 / 상태조회가능100 / 실행0 / 정지100 / 확인불가0 |
| 원천 장애 | 등록전체 미확정 / 보존100 / 조회가능99 / 정지99 / 확인불가1 |
| 자원 미할당 | 등록 과정의 RuntimeService 생성0 / Pod 생성0 |
| 시간 | 한 번의 로컬 실행5.502초; 가상 객체별 API 연속 작업 p95 88.958ms |

물리 backend는 기존 테스트의 FakeMetadata/FakeEvents다. 실제 물리 센서가 아니며 첫 Event
수신도 검증되지 않았다. 기능별 EdgeX 등록 항목을 섀시 대수로 바꾸어 부르지 않는다.
물리 조회용 트윈과 서비스/Pod를 추가로 세지 않는다. 수치는 정지 객체 포함 조건이다.
로컬 지연 수치는 네트워크·실제 EdgeX/Kubernetes 지연과 SLA를 대표하지 않는다.

추가 단위/통합시험은 100개 순수 논리 정의, 물리20+가상80의 집계와 관측 트윈 제외,
소스별 장애 격리, revision 충돌, 잘못된 자원, 실행 계약 부재, 생성 결과 미확정 후 정지,
중복 요청·재시작 후 자동 재실행 금지를 검증한다.

## 2. 병렬 실행 — 두 종류의 근거

1. 기존 Controller + 모의 Kubernetes adapter: 논리 객체4개를 동시에 시작해 서로 다른
   RuntimeService UID4개·모의 Pod4개를 만들고 실제 controller의 준비→실행→정지 경로를 시험했다.
   한 객체의 관측을 만료시켜 실행3/확인불가1/정지0을 검증했다. 실제 Pod 기동은 아니다.
2. 기존 `virtual-device-runtime/vd_runtime`을 실제 OS 프로세스4개로 같은 호스트에서 실행했다.
   실제 Iris centroid 모델, 서로 다른 ID·PID·boot ID, loopback HTTP를 사용했다.
   두 번의 동시20요청 배치에서40건, 하나만 정지 후 나머지3개 각1건,
   같은 ID로 재시작 후1건을 처리해 **총44건 성공**했다. 모델 label과 요청별 디바이스 identity를 검증했다.

프로세스 시험의 `podUid`는 null이다. Docker socket 권한이 없어 컨테이너/Pod 시험은 하지 않았다.
CPU·메모리/GPU cgroup 할당, KubeEdge 실행, 장기 부하, 모델 GPU 성능을 검증한 결과가 아니다.
실제 프로세스 시험은 새 논리 엔진의 Kubernetes 배치 경로에 연결한 E2E 실행으로 주장하지 않는다.

## 재현

저장소 루트에서 기존 aggregator 테스트 venv를 사용한다. 운영 endpoint와 kubeconfig를 사용하지 않는다.
출력은 지정한 로컬 디렉터리에만 쓴다. 성공·실패 모두 자식 실행 프로세스를 정리한다.

```bash
rtk proxy edge-orch/state-aggregator/.venv/bin/python \
  edge-orch/runtime-operator/scripts/verify_mixed_management.py \
  --output /tmp/mixed-device-management-result
```

관련 자동시험: runtime-operator 전체152개, aggregator 관련 Python99개, JavaScript313개 통과.
대시보드 시험 입력 [dashboard-fixture.json](dashboard-fixture.json)은 **모의 물리1+정지가상99**다.
운영 데이터로 사용하지 않는다. 브라우저의 원천 실패 주입도 해당 시험 응답에만 적용했다.

## 브라우저·회귀 검증

[브라우저 결과](browser-verification.json): 1440px에서100행·5개 수치·360px 목록,
390px에서280px 목록·가로 넘침 없음, 마지막 항목 검색/선택,5초 갱신 중 스크롤350px와
프로파일 입력 초안 보존을 확인했다. 응답503 주입 시 실행0/정지0/확인불가100으로 전환했다.
콘솔 오류2개는 의도적으로 주입한503이며 별도 JavaScript 예외는 없었다.

저장소 공통 시험은114개 통과/기존2개 실패다. 추진계획의140줄 제한(현재318줄)과
센서 데모 Argo targetRevision 기대값main/현행agent/edgex-central-docs 불일치다.
이 작업에서 기존 배포 branch를 변경하거나 무관한 추진계획을 축약하지 않았다.

## 최초 로컬 시험 당시 운영 인수에 남았던 조건

- 별도 승인 후 단일 노드 runtime-operator를 기존 replicas1/Recreate/PVC 구성으로 배포한다.
- 두 프로세스 쓰기 flag를 명시적으로 활성화하고 정확한 namespace/영속 경로/RBAC를 확인한다.
- 실제 EdgeX 항목을 포함한100개에 대해 등록·조회·개별 안전 제어·원천 장애·재시작 보존을 재검증한다.
- 별도 다중 실행 시험에서 실제 Pod identity와 프로파일 CPU/메모리/GPU 적용,
  독립 시작/정지·요청 응답·한 객체 장애 시 다른 객체 유지와 자원 회수를 확인한다.
- 보고서에 실제 장비/기능 endpoint/논리 객체의 구성, 정지 포함 조건과 상태별 수를 기록한다.

이 조건을 확인하기 전에는 2차년도 목표의 운영 실증 완료를 선언하지 않는다.


## 후속 재검증

[재검증과 브라우저 입력 검증 오류 수정](recheck/README.md)을 확인한다.
