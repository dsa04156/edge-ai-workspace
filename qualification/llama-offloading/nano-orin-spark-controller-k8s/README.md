# Nano·Orin·Spark 순차 데모 컨트롤러

역할은 **Nano=edge, AGX Orin=edge, 실제 DGX Spark=server**다. 정상 이동은
Nano → AGX → Spark → AGX → Nano이며 중간 단계를 건너뛰지 않는다.
기존 state-aggregator의 모델 오프로딩 transport·원장·API·추천·계획을 재사용한다.

이 overlay는 기존 대시보드를 재배포하지 않고 `llama-continuity-test`에 별도 controller를
둔다. 고정된 기존 Python app image에 해시가 붙은 ConfigMap으로 검토한 executor 모듈을
마운트한다. base image digest만으로 새 executor 코드 버전을 식별하지 말고 ConfigMap
이름·코드 SHA256도 함께 기록한다. 운영 EdgeX root나 기존 Service selector는 변경하지 않는다.

## 구성

- worker: `../nano-orin-spark-k8s`의 실제 Spark Pod와 PVC, 기존 Nano·AGX 측정 API
- controller: `ordered-offload-controller`, 1 replica·Recreate
- 읽기 전용 Kubernetes RBAC: nodes/pods get/list
- 원장: `ordered-offload-journal` PVC, 현재 `/data/runtime-v2/ordered-runtime.sqlite3`
- API: `http://ordered-offload-controller.llama-continuity-test.svc.cluster.local:18113/api/runtime-model-offloading`
- 별도 직접 추론 API token: `ordered-offload-auth` Secret의 `token` key (웹 데모 시작·중지에는 사용하지 않음)

초기 빈 원장 경로 `/data/ordered-runtime.sqlite3`는 Nano runtime label 수정 이전 기록으로
보존했다. 계약 변경 시 원장을 덮어쓰지 않으며, 접수·진행 작업이 남은 원장의 계약을
바꿔 재시작하지 않는다. 다른 CLI·프록시가 같은 모델을 동시에 제어하면 안 된다.

## 재현

새 이미지를 임의 지정하지 말고 manifest의 검증된 digest를 사용한다. Spark에는
`nvidia-spark` RuntimeClass와 `nvidia.com/gpu=1`이 필요하다. RuntimeClass 없이 생성한
첫 시도는 CPU fallback으로 거절됐으며 그 성능은 사용하지 않는다.

```bash
rtk proxy kubectl kustomize qualification/llama-offloading/nano-orin-spark-k8s --load-restrictor LoadRestrictionsNone -o /tmp/spark-worker.yaml
rtk proxy kubectl --context kubernetes-admin@kubernetes apply -f /tmp/spark-worker.yaml
rtk proxy kubectl kustomize qualification/llama-offloading/nano-orin-spark-controller-k8s --load-restrictor LoadRestrictionsNone -o /tmp/ordered-controller.yaml
rtk proxy kubectl --context kubernetes-admin@kubernetes apply -f /tmp/ordered-controller.yaml
```

고정된 저장소 내부 공용 worker/app 파일을 참조하므로 Kustomize의 load restrictor 옵션이
필요하다. 외부 입력 경로나 manifest에는 이 옵션을 적용하지 않는다.

실장비 준비와 원장 상태를 먼저 확인한 다음 **동시에 한 개의 부하 생성기만** 실행한다.
출력 경로는 기존 기록과 겹치지 않는 새 경로를 사용한다.

```bash
rtk proxy kubectl --context kubernetes-admin@kubernetes exec -i -n llama-continuity-test deployment/ordered-offload-controller -- python -u - /data/demo-run-NEW < qualification/llama-offloading/ordered_demo.py
```

스크립트가 요청을 보내며 controller가 측정 기준으로 판단한다. 스크립트는 목적지를
강제로 설정하지 않는다. 2→3.8→5.6→2.7→2 req/s로 바꿔 정상 부하·두 번의 승격·두 번의
복귀를 유도한다. SLO 자격시험 전체를 대체하는 실험이 아니라 고정 8토큰의 실제 경로
왕복 데모다. 새 서비스에는 별도의 입력 계약과 측정값이 필요하다.

완료 시 summary.json, requests.jsonl, states.jsonl이 PVC에 남는다. 실제 응답 node identity,
손실·중복·unknown, 이동 순서와 최종 상위 모델 CACHED·VRAM0을 각각 확인한다.
Pod와 GPU 예약은 유지하며, 현재보다 아래 단계의 모델은 복귀를 위해 준비 상태로 둔다.
상위 단계에서 내려온 뒤에는 해당 단계의 요청 drain과 30초 유휴를 확인해 모델만 해제한다.

## 실장비 웹 데모

- 주소: http://offload-demo.192.168.0.56.sslip.io/
- 세 노드의 처리 위치, 이번 실행의 요청 성공/실패, 모델 메모리와 실제 이동 순서를 표시한다.
- **왕복 데모 시작**을 누른다. 2026-09-10 사용자 요청으로 고정 데모 시작·중지에는 토큰 입력이 없다.
- 관측과 고정 데모 시작·중지는 토큰 없이 가능하다. 별도 직접 추론·개별 요청 조회 API의 인증은 유지한다.
- **신규 요청 중지**는 부하 생성을 중단한다. 접수 요청을 마무리하고 기존 정책에 따라 Nano로 돌아온 뒤 상위 모델 해제를 확인한다.
- 브라우저 종료와 새로고침은 서버 실행을 중단하지 않는다. 재접속하면 동일 실행을 조회한다.
- 컨트롤러 재시작 시 진행 중 UI 실행은 interrupted로 기록하며 자동 재개·재전송하지 않는다.
- UI 실행 중 별도 `/generate` API와 중복 UI 시작은 409로 거절한다. worker 직접 호출을 통한 중복 운영은 운영자가 피해야 한다.
- 고정 요청·부하만 실행한다. 임의 prompt, 모델, 목적지, node 또는 command를 입력받지 않는다.

`GET /api/demo`는 실행·관측·시작 가능 여부를 반환한다. `POST /api/demo/start`와
`POST /api/demo/stop`은 토큰 없이 호출한다. 실행 요약은 기존 PVC의 `demo-ui-run.json`에 단일 비동기 writer로 저장하고, 개별
접수 요청은 기존 SQLite FULL WAL 원장에 보관한다. UI 요약의 fsync는 관측 루프에서
실행하지 않는다. 실행 header 저장 전에는 부하를 보내지 않으며, 종료 상태도 저장한다.
화면의 합격은 고정 8토큰 1회 왕복 기준이다. 중앙 HA나 노드 단절 무손실을 뜻하지 않는다.

고정 웹 실행 동안 요청 원장의 `synchronous=FULL`은 유지하고 자동 checkpoint만
일시 중지한다. 최대 1,622건의 제한된 부하가 끝나면 별도 연결·비동기 작업으로
PASSIVE checkpoint를 수행하고 기존 자동 checkpoint 값을 복원한다. WAL checkpoint
결과는 실행 요약에 남긴다. 요약 파일과 요청 원장을 혼동하지 않는다.
