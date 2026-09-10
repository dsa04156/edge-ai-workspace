# Llama 3.2 1B 노드별 포화점 실험계획

## 목적과 판정값

동적 오프로딩 전에 각 노드의 단독 처리 한계를 먼저 고정한다. 한계는 하나의 사용률 숫자가 아니라 다음 두 값으로 보고한다.

- 처리량 knee: 관측 최대 처리량의 95%에 처음 도달한 client concurrency
- SLO capacity: 오류가 없고 p95 TTFT가 1,500ms 이하인 가장 높은 client concurrency

첫 SLO 위반 동시성을 overload onset으로 둔다. CPU/GPU 사용률은 원인 해석용이며 단독 라우팅 조건으로 사용하지 않는다.

## 실험 단위와 요인

- experimental unit: 한 역할 노드에서 실행하는 하나의 node×concurrency×block 구간
- observational unit: 개별 inference request와 1초 자원 표본
- 요인: node 역할 `nano/agx/spark`, concurrency `1/2/4/8/16/32`
- 반복: 모든 조합을 3 block에서 반복
- nuisance: 시간대, 온도, 동일 노드의 다른 workload, 네트워크 RTT
- 순서: 각 block에서 18개 조건을 seed `20260904`로 무작위화

같은 물리 노드에서 나온 요청 수백 개는 독립 하드웨어 반복이 아니다. 결과는 기술 자격시험의 분포와 block 재현성으로 해석하고 장비 모집단에 대한 유의성 검정으로 과장하지 않는다.

## 고정 조건

- 모델/runtime/digest, prompt, generation option과 max token 동일
- 각 worker의 inference concurrency 1
- 측정 전 세 역할 모두 Always-On으로 구성하고 warm-up 요청 1개 제외
- 요청 성능은 controller lock을 우회해 worker `/generate`를 직접 측정
- 자원 표본은 공통 `/metrics`를 사용해 queue, CPU, RAM, 온도와 귀속 가능한 GPU 값만 기록
- 구간 12초, 구간 완료 후 모든 요청 drain, cooldown 3초

## 정책 변환

Nano overload latch는 queue, TTFT, tokens/s를 사용한다. queue는 2초 지속 조건을 두며, TTFT는 1,500ms SLO, tokens/s는 concurrency 1 중앙값의 80%를 초기 저하 기준으로 둔다. 이 latch는 오프로딩 검토를 시작할 뿐 확정 명령이 아니다.

신규 요청은 다음 식의 gain이 양수이고 최소 15% 개선될 때만 원격 후보로 보낸다.

```text
Nano predicted completion
- (target activation + target RTT + target queue wait + target inference)
```

대상은 자체 SLO capacity 이내이고 READY여야 한다. 실행 중 generation은 이동하지 않는다.

## 중단 및 무효 기준

- 오류가 발생해 원자료에 기록되면 해당 조건을 숨기지 않는다.
- worker 또는 metrics endpoint가 준비되지 않으면 run을 실패 처리하고 원인을 수정한 뒤 새 run ID로 다시 수행한다.
- 기존 GPU workload를 중단하거나 자원을 빼앗지 않는다.
- 2026-09-04 현재 Nano는 실제 Orin Nano의 JetPack 6 CUDA 기준으로 단독 재측정했다.
  AGX·Spark 실장비는 아직 없으므로 두 역할의 GPU 결과나 원격 break-even을 만들지 않는다.
- 과거 amd64 서버 CPU 역할 대체 결과는 이력으로 보존하되 현재 Nano GPU 기준과 합쳐
  실제 세 장비 비교로 해석하지 않는다.
