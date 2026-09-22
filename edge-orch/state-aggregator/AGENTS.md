# State Aggregator 작업 지침

상위 `../AGENTS.md`와 루트 `../../AGENTS.md`를 먼저 적용한다. 이 프로젝트는 EdgeX,
Kubernetes/KubeEdge와 Prometheus의 서로 다른 권위 신호를 결합하는 read model과 운영
대시보드다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000
docker build -t state-aggregator:local .
```

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
node --test tests/*.js
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_api.py
node --test tests/test_service_designer.js
kubectl kustomize k8s >/dev/null
```

## 구조와 스타일

- `app/edgex.py`, `kube.py`, `prometheus.py` — 권위별 외부 reader
- `app/service.py`, `normalizer.py`, `models.py` — 상태 계산과 typed read model
- `app/device_management*.py` — 승인된 등록 경로; Kubernetes 쓰기는 Adapter Controller가 소유
- `app/static/` — vanilla JS/CSS 운영 UI와 브라우저 내부 서비스 설계 dry-run
- `app/config/*.json` — Git 기반 service/adapter/instance 계약
- `app/common_runtime.py`, `app/common_runtime_demo.py` — 공통 runtime 관측과 승인된 demo API 연결
- `app/static/nexus/common-runtime*.js`, `runtime-execution-map.js`, `runtime-placement-overview.js` —
  서비스 선택·지표·실행 맵·노드 후보 근거·실행/중지·부하 버튼. 배치 판단과 실행 원장은
  `../runtime-operator/`가 소유한다. 개발 현황은 `../../docs/현재-구현-상태.md`를 따른다.

Python은 타입 힌트와 명시적 오류 reason을 유지한다. JavaScript는 DOM selector와 exported
test seam을 기존 테스트와 함께 변경한다.

## Boundaries

- ✅ **Always do:** EdgeX Device/Event, node/workload, 서비스 결과의 출처와 실패 상태를 분리한다.
- 상태 판정·management API·catalog schema·정보 구조 변경은 사용자 요청 범위에서 수행한다. 이미 승인된 작업을 반복 확인하지 않고, 권한·실행 범위가 추가로 확장될 때 기존 승인이 적용되는지 확인한다.
- 🚫 **Never do:** 서비스 설계 화면에서 Kubernetes/EdgeX mutation, command, migration이나 offloading을 실행한다.

## 공통 AI 운영 화면의 현재 경계

- OFFLOAD DEMO의 승인된 서비스 실행·중지·부하 API와 서비스 설계 dry-run을 혼동하지 않는다.
  Llama 자동 증강·복귀와 새 숫자 분류 서비스의 preferred 정책을 같은 기능 수준으로 표시하지 않는다.
- 서비스 UID로 선택·지표·시험 상태를 격리한다. 이동 후 부하 제거는 처음 시작한 노드 버튼에
  유지하고, 새 반복 부하는 사용자가 시작한다. 정확한 규칙은 루트 AGENTS.md를 따른다.
- 전체 클러스터 노드와 서비스별 실행·성능 검증 후보를 구분한다. 미검증·미수집·오래된 관측을
  실행 불가·0·정상으로 임의 해석하지 않는다. 상세 판단과 제외 이유는 실제 관측을 사용한다.
