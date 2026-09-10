# Llama 3.2 1B 온디맨드 오프로딩 실험계획

## 질문과 측정 단위

세 가지 운영 방식이 요청 성능, 원격 노드 활성화 비용과 유휴 자원 점유에 어떤 차이를 만드는지 비교한다.

- 처리 조건: `always_on`, `cold_on_demand`, `cached_on_demand`
- 실행 단위: 동일한 KubeEdge 클러스터와 동일한 세 역할 노드에서 수행하는 한 실험 구간
- 관측 단위: 요청, 노드 자원 표본, 상태 전이, activation 시도
- 반복 해석: 같은 노드에서 얻은 여러 요청은 독립 장비 반복이 아니다. 유의성 검정용 독립 표본으로 취급하지 않고 기술 자격시험의 분포와 시계열로 보고한다.
- 주 반응값: 요청 latency/TTFT, throughput, activation latency, SLO violation duration, idle resource usage

## 현재 장비 역할과 제한

| 시험 행 | 실제 노드 | 현재 가속기 경계 |
|---|---|---|
| Orin Nano GPU 기준 | `etri-dev0001-jetorn` | 실제 Orin Nano, JetPack 6 CUDA, Ollama `100% GPU` 확인 |
| AGX Orin | 실장비 없음 | GPU 성능·activation·break-even 미측정 |
| DGX Spark | 실장비 없음 | GPU 성능·activation·break-even 미측정 |

Nano는 실제 GPU로 포화점을 단독 재측정했다. AGX·Spark가 준비되기 전에는 세 방식의 GPU
비교 실험을 완료로 표시하지 않는다. 과거 amd64 CPU 역할 대체 run은 실행 로직 검증 이력으로
보존하지만 실제 AGX·Spark 결과가 아니다. Nano의 GPU utilization/memory는 현재 Jetson용
DCGM collector가 없어 결측으로 유지하며 0으로 대체하지 않는다.

## 고정 조건

- 모델: 세 역할 모두 `llama3.2:1b`, activation마다 digest 검증
- runtime: 동일 Ollama multi-architecture image digest
- generation: temperature 0, seed 42, context 2,048, 동일 prompt와 max token
- worker concurrency: 역할별 1
- 동적 정책: queue/TTFT/tokens-per-second, 2초 overload dwell, 15% predicted E2E 개선 gate, 5초 cooldown
- 예측 비용: RTT + queue wait + inference + 비활성 대상의 예상 activation 비용
- idle timeout: 30초
- READY 전 요청 전달 금지, 실행 중 요청 migration 및 layer 분할 금지

## 비교 방식

| 방식 | Nano | AGX | Spark | 유휴 시 원격 모델 |
|---|---|---|---|---|
| Always-On | ACTIVE | ACTIVE | ACTIVE | runtime과 모델 메모리 유지 |
| Cold On-Demand | ACTIVE | COLD | COLD | inference runner 정지, local model 삭제 |
| Cached On-Demand | ACTIVE | CACHED | CACHED | inference runner 정지, local model 유지 |

경량 control API와 Ollama 관리 데몬은 계속 실행된다. 여기서 `worker 미실행`은 토큰을 생성하고 모델 메모리를 점유하는 Ollama runner가 없다는 뜻이며 관리 데몬은 포함하지 않는다. 모델 cache는 runtime container의 로컬 writable layer에 유지되므로 같은 Pod 안의 runner 재활성화에는 사용되지만 Pod 재생성 내구성은 보장하지 않는다. 이 경계는 KubeEdge edge Pod에서 현재 Pod의 `emptyDir` 원본이 삭제된 채 마운트되는 현상을 실측한 뒤 선택했다. 따라서 `worker_start_ms`는 관리 데몬 준비 확인 시간이고, 실제 runner 시작과 CUDA 초기화는 Ollama가 별도 시점을 노출하지 않아 `model_load_ms`에 포함한다.

## 실험 블록과 순서

시간·온도·다른 cluster workload를 nuisance factor로 기록한다. 한 물리 클러스터만 있으므로 방법을 동시에 실행하지 않고, 실험 종류를 block으로 삼아 방법 순서를 바꾼다. schedule seed는 `20260904`다.

| block | workload | method order |
|---|---|---|
| idle | 요청 없음, 방식별 5분, 1초 목표 표본 | Cached → Always-On → Cold |
| single | 동시 요청 1 | Always-On → Cold → Cached |
| increasing | 1,2,4,8,16,32, 각 15초 | Cold → Cached → Always-On |
| burst | 1×30초 → 16×30초 → 2×60초 | Cached → Cold → Always-On |
| repeated burst | 1→16→1→16→1, 저부하 35초·고부하 20초 | Cold → Always-On → Cached |

각 block/method 시작 전에 method 상태를 명시적으로 구성하고 상태 readback을 확인한다. Cold와 Cached의 사전 구성 시간은 workload 성능에서 제외하고 별도 setup log로 보존한다. 실제 activation은 workload 중 overload 판단으로 시작한다.

### 2026-09-04 혼합 장비 CPU-only run 편차

실제 보존 run은 `Cached → Always-On → Cold`의 method-grouped 순서로 수행했다. Cold가 local checkpoint를 삭제하므로 block마다 순서를 바꾸면 같은 1.3GB 모델을 반복 다운로드해야 했고, 네트워크 상태가 activation 비교에 더 크게 섞이는 것을 피하기 위한 실행상 선택이다. 따라서 이 run은 위 block 순서를 충족하지 않으며 시간 경과·열 상태의 순서 효과가 남는다. 실장비 최종시험은 위 block 순서와 반복 수를 적용해야 한다.

## SLO와 분석

- 자격시험 SLO: TTFT 1,500ms 이하
- SLO violation duration: 첫 위반 요청 선택 시각부터 TTFT가 정상 범위로 회복된 첫 후속 요청 완료까지
- break-even gain:

```text
nano 예상 처리시간 - (remote activation + network + remote inference)
```

`gain > 0`인 최초 backlog/request horizon을 method와 target별로 계산한다. Activation을 일으키지 않은 짧은 burst도 정책의 정상 결과로 보존하며 강제로 원격 실행시키지 않는다.

## 원시 증거와 시각화

- request CSV: 요청 선택과 실제 성능
- resource CSV: method/state별 CPU/RAM/GPU/process RSS/cache size 시계열
- activation CSV: worker start, remote/download, model load, endpoint ready 시간
- transition CSV: COLD/CACHED/ACTIVE 상태 전이와 사유
- 그래프는 원시 CSV에서만 생성하고 값 누락을 0으로 대체하지 않는다.
- 세 방식은 색상뿐 아니라 marker와 line style을 함께 사용한다.
