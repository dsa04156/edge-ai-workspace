# AI 서비스 자원 증강 부하 실험

## 결론

2026-08-18 테스트베드에서 `sensor-anomaly-demo`의 Device1 로컬 추론과 Server1 CUDA
후보를 90회 실행해 비교했다. 현재 모델 조합
`baseline-1.0.0` → `cuda-baseline-1.0.0`은 **Server1 전환 대상으로 부적합**하다.
45개 대응쌍 모두에서 Server1의 p95 처리 지연이 더 길었고, 처리량 우위도 한 번도 없었다.
따라서 현재 운영 경로는 Device1 로컬을 유지한다.

이 결과는 GPU 오프로딩 일반이 효과가 없다는 뜻이 아니다. 현재 통계 기준선의 계산량이
작아 HTTP·직렬화·네트워크 비용이 지배적이라는 뜻이다. 옥동 학습 모델이 준비되면 같은
절차로 모델 버전별 자격을 다시 판정해야 한다.

## 질문과 가설

- 질문: CPU·메모리·입력률 부하에서 Server1 후보가 로컬보다 지연을 줄이면서 처리량을
  유지하는가?
- 대립 가설: Server1의 p95 지연이 로컬보다 낮다.
- 경쟁 설명: 모델 계산량이 너무 작아 원격 호출 비용이 GPU 이득보다 크다.

향후 후보 승격 기준은 조건별로 다음을 모두 만족하는 것으로 고정했다.

1. 동일 입력과 정확한 source/candidate model version을 비교하고 응답 version을 검증한다.
2. Server1 p95 지연이 로컬보다 10% 이상 개선된다.
3. Server1 처리량이 로컬보다 5% 넘게 낮아지지 않는다.
4. 검증하기로 선택한 운영 범위의 모든 조건에서 2번과 3번을 통과하고 error와 OOM이 0건이다.
5. endpoint readiness, 승인 주체와 rollback 책임을 별도로 확인한다.

이 10%/5% 값은 향후 운영 승격을 위한 실용적 마진이며, 이번 결과에서 사후 추정한 통계적
임계값이 아니다.

## 실험 설계

| 항목 | 설정 |
|---|---|
| 실험 ID | `sensor-augmentation-20260818` |
| 실행 위치 | Device1 `etri-dev0001-jetorn`의 동일 실험 Pod/cgroup |
| 로컬 처리 | `online-baseline` · `baseline-1.0.0` |
| 원격 후보 | Server1 `cuda-online-baseline` · `cuda-baseline-1.0.0` |
| Pod 제한 | CPU 250m, memory 128Mi |
| 처리율 | 1, 50, 200 request/s |
| CPU 부하 | limit 대비 0, 25, 50, 75, 100% 조합 |
| 추가 메모리 | 0, 32, 64, 80MiB |
| 반복 | 조건·경로별 3회, 무작위 block 순서 |
| 실행 시간 | CPU 실험 10초, 메모리 실험 8초, run 사이 2초 washout |
| 총량 | 15조건, 90 runs, local/server1 대응쌍 45개 |

운영 서비스 route는 바꾸지 않았다. 실험 Pod에만 임시 NetworkPolicy를 적용해 Server1
endpoint를 호출했고, 종료 후 Job·ConfigMap·NetworkPolicy를 제거했다. 측정값은 p95 처리
지연, 처리량, 요청 schedule lag, CPU saturation/throttle, peak memory, error와 OOM이다.

## 주요 결과

아래 값은 각 조건의 3회 반복 중앙값이다.

| 부하 조건 | Device1 p95 | Server1 p95 | Device1 처리량 | Server1 처리량 | 해석 |
|---|---:|---:|---:|---:|---|
| 1 rps, CPU 0% | 1.252 ms | 20.108 ms | 약 1.00/s | 약 1.00/s | 로컬이 약 16배 짧음 |
| 1 rps, CPU 100% | 2.302 ms | 25.616 ms | 약 1.00/s | 약 1.00/s | 로컬이 약 11배 짧음 |
| 50 rps, CPU 0% | 0.496 ms | 9.553 ms | 50.096/s | 50.071/s | 처리량 유사, 지연은 로컬 우세 |
| 50 rps, CPU 100% | 0.511 ms | 72.177 ms | 50.095/s | 49.193/s | Server1 지연·schedule lag 증가 |
| 200 rps, CPU 0% | 0.310 ms | 60.952 ms | 200.106/s | 84.097/s | Server1이 목표 처리율 미달 |
| 200 rps, CPU 100% | 0.322 ms | 81.575 ms | 200.104/s | 49.439/s | Server1 병목이 가장 뚜렷함 |

메모리 실험에서 추가 메모리 0/32/64/80MiB일 때 Device1 peak memory 중앙값은 각각
33.2/63.9/98.7/114.0MiB였다. 그러나 Device1 p95는 0.447–0.542ms, 처리량은 약 50.12/s를
유지했다. Server1 p95는 약 9.44–9.67ms로 모든 조건에서 더 길었다. error와 OOM은 총 0건이다.

50 rps Server1 실행 중 `nvidia-smi`를 1초 간격으로 6회 관측했을 때 GPU utilization과
memory utilization은 모두 0%였고 프로세스 GPU memory는 264MiB였다. 짧은 표본이므로
정밀 GPU 사용률 연구로 해석하지 않지만, 현재 계산이 GPU 이득을 만들 만큼 크지 않다는
실험 결과와 일치한다.

## 통계 해석

서로 다른 부하 조건을 같은 정규분포로 가정하지 않고, 대응된 local/server1 run의 방향만
보는 exact two-sided sign test를 사용했다.

- Server1 p95 우위: 0/45 pairs, 양측 p = `5.7e-14`
- Server1 처리량 우위: 0/45 pairs, 양측 p = `5.7e-14`
- 승격 기준 통과: 0/15 conditions

이는 이번 범위에서 방향이 일관됐다는 근거다. 조건별 반복이 3회이고 실행 시간이 짧으며
실제 옥동 모델·현장 네트워크·장시간 열화는 포함하지 않았으므로, 효과 크기나 공장 운영
SLA를 확정한 결과로 확대 해석하지 않는다.

## 운영 판단 기준

자원 사용률만 높다고 곧바로 오프로딩하지 않는다. 대시보드의 read-only 판단은 두 종류의
압력이 동시에 지속될 때만 후보 검토 단계로 올라간다.

| 판단 축 | 기준 | 지속 시간 | 의미 |
|---|---|---:|---|
| 자원 압력 | CPU 85% 이상 또는 memory 85% 이상 | 300초 | 일시 spike를 제외한 조사 시작 기준 |
| 서비스 압력 | p95 4,000ms 이상, backlog > 0, 또는 throughput < 0.8/s | 180초 | 현재 약 1Hz 서비스 budget 저하 |
| 후보 자격 | 정확한 모델 버전이 10% 지연 개선·5% 처리량 비열등·오류 0 기준 통과 | 실험별 | 자원 압력과 별개인 전환 gate |

CPU/memory 85%, 300초와 서비스 180초 기준은 보수적인 관찰·debounce 정책이다. 이번 짧은
부하 실험이 이 숫자를 최적 임계값으로 증명한 것은 아니다. 두 압력이 지속돼도 후보 자격이
`rejected`이면 `BLOCKED`로 표시한다. 자격이 `qualified`여도 화면은 `RECOMMENDED` 판단만
제공하며 자동 배포·라우팅·migration을 실행하지 않는다.

## 재현과 다음 검증

```bash
python3 tools/sensor_augmentation_experiment.py --help
python3 tools/analyze_sensor_augmentation_experiment.py \
  artifacts/sensor-augmentation/*.json \
  --output artifacts/sensor-augmentation/summary-20260818.json
edge-orch/state-aggregator/.venv/bin/python -m pytest -q \
  tests/test_sensor_augmentation_experiment.py
kubectl create --dry-run=client --validate=false \
  -f tools/k8s/sensor-augmentation-experiment.yaml -o yaml >/dev/null
```

원시 JSON은 `artifacts/sensor-augmentation/`의 로컬 실험 증거이며 Git 공개 문서 세트에는
포함하지 않는다. 스크립트, Kubernetes 실험 manifest, 판정기와 이 보고서는 버전 관리한다.

다음 승격 시험은 옥동 실제 모델과 입력 계약을 고정한 뒤 30분 이상 endurance, 실제 E2E
수집 주기, network loss/timeout, GPU utilization·전력, 실패 시 local rollback을 포함한다.
후보가 바뀌면 `ServiceDescriptor.augmentation_qualification`을 자동 변경하지 않고 실험
보고서 검토 후 명시적으로 갱신한다.
