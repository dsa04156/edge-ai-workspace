# AI 서비스 자원 증강 부하 실험

## 결론

> **장치별 핵심 결론:** 대표 temporal-convolution 성능 프록시에서 Raspberry Pi 5는
> 약 1,180만 연산/frame 이상이고 실험 Pod CPU가 95% 이상 포화되며, 로컬 p95가
> 90ms 이상이거나 처리량이 20/s 이하일 때 Server1 오프로딩이 유리했다.
>
> 이 기준은 동일 model version의 Server1이 지연 10% 개선·처리량 5% 비열등 gate를
> 통과하고 상태가 기존 180초 debounce 동안 지속될 때 `RECOMMENDED`를 만드는 근거다.
> 학습된 옥동 모델의 운영 자격이나 자동 전환 승인을 뜻하지 않는다.

2026-08-18 테스트베드에서 EdgeX Local Data v3로 실제 유입된 `arduino-001` Reading
120개 frame을 캡처하고, 같은 입력을 Device1 로컬 추론과 Server1 CUDA 후보에 고정해
1·50·200 rps에서 총 18회 비교했다. 현재 모델 조합
`baseline-1.0.0` → `cuda-baseline-1.0.0`은 **Server1 전환 대상으로 부적합**하다.
9개 대응 run 모두에서 Server1의 p95 엣지 판단 E2E 지연이 더 길었고 처리량 우위도 없었다.
실제 유입 속도에 가까운 1 rps에서도 로컬 1.265ms, Server1 15.633ms였으며, 200 rps
가속 재생에서는 Server1 처리량이 84.389/s로 막히고 schedule lag p95가 5.450초까지
증가했다. 따라서 현재 운영 경로는 Device1 로컬을 유지한다.

앞서 수행한 합성 입력 90 runs/45 pairs와 왕복 계측 확인 18 runs도 같은 방향이었다.
그 결과는 부하 축 탐색과 계측 검증 근거로 유지하되, 현재 연결된 장비의 데이터에 대한
판정은 위 실데이터 캡처·재생 실험을 우선 근거로 삼는다.

이 결과는 GPU 오프로딩 일반이 효과가 없다는 뜻이 아니다. 현재 통계 기준선의 계산량이
작아 HTTP·직렬화·네트워크 비용이 지배적이라는 뜻이다. 옥동 학습 모델이 준비되면 같은
절차로 모델 버전별 자격을 다시 판정해야 한다.

별도의 대표 temporal-convolution 부하 실험에서는 계산량이 약 1,180만 element 연산/추론인
구간부터 Device1 CPU 병목과 Server1 이득이 함께 관측됐다. 이 값은 실제 Arduino 입력으로
측정한 **모델 크기별 용량 계획 근거**지만 학습된 옥동 모델의 운영 자격은 아니다.
같은 모델과 실데이터를 Raspberry Pi 5 `etri-dev0003-raspi5`에서도 재생한 후속 비교에서는
약 1,180만 연산 프로필의 12개 대응 run 모두 Server1이 지연·처리량 gate를 통과했다.

## 자원 증강 기준치 설계

자원 증강 여부는 CPU나 메모리 사용률 하나만으로 결정하지 않는다. **자원 압력, 서비스
성능 저하, 동일 모델의 Server1 개선 효과**를 순서대로 확인하며, 일시적인 spike를 제외하기
위해 지속시간을 적용한다.

### 기준치 표

| 판단 단계 | 기준치 | 지속시간 | 판단 및 조치 |
|---|---|---:|---|
| 자원 압력 관찰 | CPU 85% 이상 또는 메모리 85% 이상 | 300초 | 원인 조사를 시작한다. 이 값은 보수적인 운영 정책이며 실험으로 최적화한 전환 임계값은 아니다. |
| 서비스 성능 저하 관찰 | p95 4,000ms 이상, backlog 발생 또는 처리량 0.8건/s 미만 | 180초 | 현재 약 1Hz 기준선 서비스의 성능 저하 여부를 확인한다. |
| Raspberry Pi 장치별 병목 | 약 1,180만 연산/frame 이상 **그리고** CPU 포화도 95% 이상 **그리고** 로컬 p95 90ms 이상 또는 처리량 20건/s 이하 | 180초 | 동일 모델의 Server1 후보 자격 시험을 확인한다. |
| Server1 후보 자격 | 로컬 대비 p95 지연 10% 이상 개선, 처리량 감소 5% 이내, 오류·OOM 0건 | 실험별 | 모두 통과하면 `RECOMMENDED`, 통과하지 못하면 `BLOCKED`로 표시한다. |

### 실험 근거

1. **실데이터 사용:** EdgeX를 통해 실제 유입된 `arduino-001` Reading 120개를 고정하고
   로컬과 Server1에 같은 순서로 재생했다. 따라서 두 경로의 입력 차이를 제거했다.
2. **가벼운 기준선 모델:** 실제 입력에 가까운 1 RPS에서 로컬은 1.265ms, Server1은
   15.633ms였다. 계산량이 작으면 네트워크·HTTP 왕복 시간이 더 크므로 현재 운영 경로는
   로컬 처리를 유지한다.
3. **약 295만 연산 대표 모델:** 일부 조건에서 Server1이 빨랐지만 부하 전 범위에서 결과가
   일정하지 않았다. Raspberry Pi의 개별 run gate 통과도 5/12에 그쳐 오프로딩 기준으로
   채택하지 않았다.
4. **약 1,180만 연산 대표 모델:** Raspberry Pi의 로컬 p95가 약 90~196ms, 처리량이 약
   6~20건/s로 저하됐다. 동일 입력 12회 비교에서 Server1이 모두 지연 우위를 보였고 12/12
   run이 후보 gate를 통과했다. 중앙값 기준 지연은 48.7% 감소하고 처리량은 3.806배로
   증가했으며, 지연 방향 양측 sign test는 `p=0.000488`이었다.
5. **전체 경로 측정:** Server1 지연에는 요청 직렬화, 네트워크 전송, 서버 처리와 결과 반환을
   모두 포함했다. 서버 내부 추론 시간만 비교해 오프로딩 효과를 과대평가하지 않았다.

여기서 `RPS`는 1초에 들어오는 요청 수이고 `처리량`은 1초에 실제로 완료한 요청 수다.
예를 들어 50 RPS가 들어오는데 처리량이 20건/s라면 초당 약 30건이 대기열에 쌓인다.
`p95 90ms`는 요청 100개 중 약 95개가 90ms 안에 끝나고, 느린 쪽 약 5개는 그보다 오래
걸린다는 뜻이다.

### 보고서 결론

> Raspberry Pi 5에서 약 1,180만 연산급 모델을 실행할 때 CPU가 95% 이상 포화되고,
> 로컬 p95가 90ms 이상이거나 처리량이 초당 20건 이하로 떨어지는 상태가 180초 이상
> 지속되면 Server1 오프로딩을 검토한다. 단, 동일 모델의 Server1이 지연을 10% 이상
> 개선하고 처리량 감소를 5% 이내로 유지하며 오류·OOM이 없을 때만 자원 증강을
> `RECOMMENDED`로 권고한다.

이 결론은 자동 전환 명령이 아니다. 현재 화면은 운영자에게 판단 근거만 제공하며 워크로드
이동이나 요청 경로 변경을 실행하지 않는다. 또한 약 1,180만 연산 모델은 실제 센서 값으로
계산 부하를 비교한 성능 프록시이므로, 실제 옥동 학습 모델이 준비되면 같은 절차로 기준치를
다시 검증해야 한다.

## 질문과 가설

- 질문: CPU·메모리·입력률 부하에서 Server1 후보가 로컬보다 지연을 줄이면서 처리량을
  유지하는가?
- 대립 가설: Server1의 p95 지연이 로컬보다 낮다.
- 경쟁 설명: 모델 계산량이 너무 작아 원격 호출 비용이 GPU 이득보다 크다.

향후 후보 승격 기준은 조건별로 다음을 모두 만족하는 것으로 고정했다.

1. 동일 입력과 정확한 source/candidate model version을 비교하고 응답 version을 검증한다.
2. 같은 엣지 입력 준비 시점부터 결과가 엣지에 돌아올 때까지 잰 Server1 p95 지연이
   로컬보다 10% 이상 개선된다.
3. Server1 처리량이 로컬보다 5% 넘게 낮아지지 않는다.
4. 검증하기로 선택한 운영 범위의 모든 조건에서 2번과 3번을 통과하고 error와 OOM이 0건이다.
5. endpoint readiness, 승인 주체와 rollback 책임을 별도로 확인한다.

이 10%/5% 값은 향후 운영 승격을 위한 실용적 마진이며, 이번 결과에서 사후 추정한 통계적
임계값이 아니다.

## 실데이터 범위와 계보

이번 입력은 simulator에서 만든 값이 아니다. `etri-dev0001-jetorn`에서 실행 중인
`device-serial-jetson`이 물리 source `arduino-001`에서 수집해 Local Data v3로 제공한
가속도 X/Y/Z와 온도 Reading이다. EdgeX Device 이름에 `virtual-` 접두사가 있어도 이
프로젝트에서 그것은 기능별 fan-out Device 이름이며, 입력의 물리 source ID는
`arduino-001`이다.

- 캡처 시각: `2026-08-18T07:06:02.169004Z`
- frame 수: 120개, 최신 frame age: 0.526초
- frame `origin`: `1787036640557005353`–`1787036761643232960`
- 데이터셋 SHA-256: `2ea31280335eeb6d71e2ce14366388bbbe442a2c7f4a8cf554a0810d552750e3`
- 값 범위: X 285–295, Y 219–223, Z 247–256, 온도 278–288
- 온도 정렬 오차: p50 12.014ms, p95 12.379ms, 최대 12.674ms

X/Y/Z는 동일한 EdgeX `origin`으로 exact join했고 온도는 서비스의 context-skew 계약 안에서
가장 가까운 Reading을 결합했다. 캡처 데이터셋 하나를 18개 run 모두에 동일하게 사용하고
각 run의 데이터셋 해시를 검증했으므로 입력 차이가 경로 차이와 섞이지 않는다. 1 rps는 현재
관측되는 약 1Hz 입력 주기에 대응한다. 50·200 rps는 **실제 측정값을 가속 재생한 부하**이며
장비가 원래 그 속도로 발행했다는 뜻은 아니다.

이 실데이터는 현재 연결된 Arduino 수직 슬라이스의 데이터다. 아직 제공되지 않은 옥동
PLC·MES 생산 데이터나 실제 유압펌프·모터 학습 모델의 결과로 설명하지 않는다.

## 엣지 컴퓨팅 비교 경계

로컬 처리와 서버 처리는 시작점과 종료점을 같게 두어야 한다. 현재 실험의 시작점은
`Device1에서 입력 frame이 준비된 시점`, 종료점은 `판단 결과를 Device1에서 사용할 수 있는
시점`이다.

- 로컬 전체 지연: `센서→엣지 입력 준비 + 엣지 입력 구성·로컬 추론`
- 서버 전체 지연: `센서→엣지 입력 준비 + 요청 직렬화·업로드 + 서버 대기·추론 + 응답
  다운로드·파싱`

두 경로에 공통인 `센서→엣지 입력 준비` 구간은 후보 비교에서는 상쇄되므로, 승격 gate는
분기 이후의 `edge_decision_e2e_latency_ms`를 사용한다. 단, 현장 KPI에는 공통 수집 지연도
별도로 표시한다. 물리 센서 `origin`과 엣지 시계의 동기화가 검증되지 않았다면 이 구간을
분기 지연에 합산하지 않는다. 서버가 중앙 데이터 소스를 직접 읽는 별도 구조라면 공통 구간이
아니므로 센서 원시 시점부터 결과 소비 지점까지 다시 E2E 측정해야 한다.

Server1 응답의 `serverProcessingMs`는 API request parsing 이후 fingerprint, lock 대기와 모델
처리를 잰다. `edge_decision_e2e_latency_ms - serverProcessingMs`는 엣지 요청 구성·직렬화,
양방향 네트워크, HTTP parsing·response serialization과 엣지 응답 parsing을 포함하는 왕복
오버헤드다. 서로 다른 p95 분위수끼리는 산술적으로 정확히 더해지지 않으므로 각 항목을 독립
지표로 해석한다.

## 기존 합성 입력 부하 축 탐색

| 항목 | 설정 |
|---|---|
| 실험 ID | `sensor-augmentation-20260818` |
| 실행 위치 | Device1 `etri-dev0001-jetorn`의 동일 실험 Pod/cgroup |
| 입력 | 고정 규칙으로 생성한 합성 frame(부하 축 탐색용) |
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
endpoint를 호출했고, 종료 후 Job·ConfigMap·NetworkPolicy를 제거했다. 측정값은 엣지 입력
준비부터 결과 반환까지의 p95 E2E 지연, 처리량, 요청 schedule lag, CPU
saturation/throttle, peak memory, error와 OOM이다.

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

위 90회 실험은 Device1 실험 Pod가 로컬 함수를 호출하거나 Server1 HTTP 응답을 기다리는 전체
호출을 동일하게 계측했으므로 Server1 값에 직렬화·네트워크·응답 반환이 이미 포함되어 있다.
다만 당시 `v1` 산출물은 서버 내부 처리와 왕복 오버헤드를 분리하지 않았다.

메모리 실험에서 추가 메모리 0/32/64/80MiB일 때 Device1 peak memory 중앙값은 각각
33.2/63.9/98.7/114.0MiB였다. 그러나 Device1 p95는 0.447–0.542ms, 처리량은 약 50.12/s를
유지했다. Server1 p95는 약 9.44–9.67ms로 모든 조건에서 더 길었다. error와 OOM은 총 0건이다.

50 rps Server1 실행 중 `nvidia-smi`를 1초 간격으로 6회 관측했을 때 GPU utilization과
memory utilization은 모두 0%였고 프로세스 GPU memory는 264MiB였다. 짧은 표본이므로
정밀 GPU 사용률 연구로 해석하지 않지만, 현재 계산이 GPU 이득을 만들 만큼 크지 않다는
실험 결과와 일치한다.

## 합성 입력 엣지↔서버 왕복 분해 확인

2026-08-18에 계측 필드를 추가한 Server1 image
`sha256:b31d45e138c431cc3f6a04be5757b0244942338cd2387b01ef7825359f464c1c`를 배포하고,
Device1에서 CPU·메모리 추가 압력 없이 1·50·200 rps를 경로별 3회씩, 총 18 runs 재실행했다.
이 확인 실험도 합성 frame을 사용했다. 측정 범위와 지연 구성요소를 확인하는 목적이며 앞의
90회 후보 자격 실험이나 뒤의 실데이터 실험을 대체하지 않는다.

| 목표 입력률 | 로컬 E2E p95 | Server1 E2E p95 | Server1 내부 p95 | 왕복 오버헤드 p95 | 로컬/서버 처리량 |
|---:|---:|---:|---:|---:|---:|
| 1 rps | 1.300 ms | 18.541 ms | 3.070 ms | 16.130 ms | 1.100 / 1.098/s |
| 50 rps | 0.438 ms | 9.144 ms | 2.723 ms | 6.877 ms | 50.093 / 50.068/s |
| 200 rps | 0.286 ms | 60.902 ms | 2.690 ms | 59.872 ms | 200.085 / 82.277/s |

각 값은 3회 run의 p95 중앙값이다. 총 error는 0건이었다. Server1 E2E p95는 로컬 대비
각각 14.3배, 20.9배, 213.0배였고, 200 rps에서는 처리량도 로컬의 약 41.1%에 그쳤다.
현재 소형 모델에서는 서버 내부 계산보다 왕복/API 경로 비용이 더 크며 높은 입력률에서는
전송·HTTP queue를 포함한 경로 병목이 확대된다는 근거다. 따라서 이 후보를 오프로딩하면
개선되는 것이 아니라 오히려 느려진다는 기존 `rejected` 판정을 유지한다.

## 실제 Arduino 데이터 비교 결과

같은 날 실제 Arduino Reading 120개를 한 번 캡처한 뒤 CPU·메모리 추가 압력 없이
1·50·200 rps를 경로별 3회씩 무작위 block 순서로 실행했다. Pod 제한은 CPU 250m,
memory 128Mi이고 각 run은 10초, washout은 2초다. 운영 route는 변경하지 않았다.

| 목표 입력률 | 로컬 E2E p95 | Server1 E2E p95 | Server1 내부 p95 | 왕복 오버헤드 p95 | 로컬/서버 처리량 | 서버 schedule lag p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 rps | 1.265 ms | 15.633 ms | 2.965 ms | 12.840 ms | 1.100 / 1.098/s | 0.789 ms |
| 50 rps | 0.496 ms | 9.417 ms | 2.688 ms | 7.253 ms | 50.095 / 50.056/s | 0.116 ms |
| 200 rps | 0.299 ms | 60.375 ms | 2.620 ms | 59.619 ms | 200.085 / 84.389/s | 5,450.371 ms |

각 값은 독립 실험 단위인 3개 run의 p95 중앙값이다. run 내부의 개별 요청을 독립 반복으로
간주하지 않았다. error와 OOM은 모두 0건이었지만 Server1은 세 입력률 모두에서 10% 지연
개선 기준을 통과하지 못했고, 200 rps에서는 5% 처리량 비열등 기준도 통과하지 못했다.
200 rps Server1 경로의 CPU saturation 중앙값은 1.013, throttled time 중앙값은 6.000초로
요청 경로가 공급 속도를 따라가지 못했다. Server1 내부 처리 p95는 2.620ms였지만 엣지에서
결과를 받기까지의 왕복 오버헤드 p95가 59.619ms였으므로 판단은 내부 추론 시간만으로 하면
안 된다.

대응 run의 exact two-sided sign test에서 Server1 지연 우위는 0/9
(`p=0.00390625`), 처리량 우위도 0/9(`p=0.00390625`)였다. 다만 조건별 반복은 3회이고
짧은 실행이므로 이 결과를 장시간 운영 SLA나 옥동 모델 성능으로 일반화하지 않는다.

## 대표 AI 모델의 병목·오프로딩 교차점

실제 옥동 학습 모델 파일이 아직 없으므로 운영 baseline을 억지로 무겁게 만들지 않고,
센서 시계열 모델의 계산부를 나타내는
`representative-temporal-convolution-v1`을 별도 성능 proxy로 실행했다. 256개 실측 특성을
입력으로 받고 20개 temporal-convolution layer를 CPU NumPy와 Server1 CuPy에서 동일하게
계산한다. 가중치는 결정적이지만 학습되지 않았으므로 이상감지 정확도나 실제 옥동 모델
성능의 근거로 사용하지 않는다.

- 입력: `arduino-001`의 실제 EdgeX Reading 120 frames
- 데이터셋 SHA-256: `bb9ee7bc3edc6910a0402493d8e88757981e44fceefcb083e5c79f96f0b79b77`
- Device1 제한: CPU 250m, memory 512MiB
- 설계: 모델 크기·CPU 경쟁 부하·처리 경로의 seeded randomized block
- 반복: 조건·경로별 3 runs, run당 10 requests
- 비교 gate: Server1 p95 10% 이상 개선, 처리량 5% 비열등

아래 값은 각 조건의 3개 run-level p95 중앙값이다.

| 모델 activation / 연산량 | Device1 CPU 경쟁 부하 | 로컬 p95 | Server1 p95 | 지연 개선 | 로컬/서버 처리량 | 판정 |
|---|---:|---:|---:|---:|---:|---|
| 16,384 / 약 295만 | 0% | 84.756ms | 21.439ms | 74.7% | 37.630 / 111.861/s | 통과 |
| 16,384 / 약 295만 | 50% | 84.026ms | 83.937ms | 0.1% | 31.538 / 31.055/s | 거부 |
| 16,384 / 약 295만 | 75% | 86.612ms | 83.250ms | 3.9% | 24.515 / 26.083/s | 거부 |
| 16,384 / 약 295만 | 100% | 93.510ms | 98.079ms | -4.9% | 19.833 / 17.391/s | 거부 |
| 65,536 / 약 1,180만 | 0% | 175.610ms | 48.759ms | 72.2% | 9.969 / 83.413/s | 통과 |
| 65,536 / 약 1,180만 | 50% | 104.096ms | 87.223ms | 16.2% | 10.053 / 33.025/s | 통과 |
| 65,536 / 약 1,180만 | 75% | 99.620ms | 83.250ms | 16.4% | 12.234 / 26.677/s | 통과 |
| 65,536 / 약 1,180만 | 100% | 193.101ms | 90.710ms | 53.0% | 6.707 / 20.598/s | 통과 |

약 295만 연산 모델은 CPU 경쟁 부하가 생기면 원격 요청을 만드는 Device1 클라이언트도 함께
throttling되어 4개 조건 중 1개만 통과했다. 반면 약 1,180만 연산 모델은 네 조건 모두
조건 중앙값 gate를 통과했다. 이 모델의 12개 대응 run 중 Server1 지연 우위와 개별 run gate
통과는 각각 11/12였고, 지연 방향 exact two-sided sign test는 `p=0.00634765625`였다.
대응 run 지연 감소율 중앙값은 40.9%, 처리량 비율 중앙값은 3.105배였다.

따라서 이 대표 모델에서 병목은 **약 1,180만 연산의 temporal feature 계산이 Device1 250m
CPU quota를 포화시키고 throttling을 만드는 구간**이다. Server1 내부 p95는 조건 중앙값 기준
2.98–7.11ms였고 나머지는 Device1 요청 처리와 왕복 비용이었다. 계산량이 충분히 크면 이
고정 비용보다 GPU 계산 이득이 커져 오프로딩 교차점이 생긴다.

### Jetson·Raspberry Pi·Server1 동일 입력 비교

후속 비교는 Jetson에서 실제 Arduino Reading 120개를 한 번만 캡처하고, 그 JSON과 SHA-256을
Raspberry Pi에 전달해 동일 순서로 재생했다. 두 엣지는 모두 같은 arm64 image, CPU 250m,
memory 512MiB, 모델 크기, CPU 경쟁 부하, seed, 반복 수를 사용했다. Jetson과 Raspberry Pi
Job은 Server1 GPU 경쟁을 피하려고 순차 실행했으며 운영 추론 포트와 route는 변경하지 않았다.

- 캡처 시각: `2026-08-18T08:34:25.047569Z`
- 데이터셋 SHA-256: `f728f12378126176c8df4a66c2e5f422337c0cc4882e0d116eb1f1b36f681bc5`
- frame `origin`: `1787041943945871517`–`1787042065032288393`
- 실행 노드: Jetson `etri-dev0001-jetorn`, Raspberry Pi 5 `etri-dev0003-raspi5`
- 독립 반복: 노드·모델 크기·부하·경로별 3 runs, run당 요청 10개

약 1,180만 연산 프로필의 조건별 3개 run 중앙값은 다음과 같다.

| 엣지 | CPU 경쟁 부하 | 로컬 p95 | Server1 p95 | 로컬/서버 처리량 | 로컬 CPU 포화 | 로컬 throttle | 판정 |
|---|---:|---:|---:|---:|---:|---:|---|
| Jetson Device1 | 0% | 102.815ms | 38.807ms | 9.972 / 104.450/s | 102.6% | 0.744s | 통과 |
| Jetson Device1 | 50% | 185.314ms | 76.241ms | 8.336 / 33.561/s | 100.5% | 1.745s | 통과 |
| Jetson Device1 | 75% | 99.698ms | 89.793ms | 12.206 / 21.173/s | 108.4% | 1.296s | 경계 거부 |
| Jetson Device1 | 100% | 194.915ms | 97.494ms | 6.641 / 14.651/s | 99.2% | 2.526s | 통과 |
| Raspberry Pi 5 | 0% | 89.739ms | 12.848ms | 19.798 / 161.721/s | 104.9% | 0.226s | 통과 |
| Raspberry Pi 5 | 50% | 96.013ms | 61.590ms | 15.178 / 86.781/s | 105.7% | 0.583s | 통과 |
| Raspberry Pi 5 | 75% | 97.719ms | 74.180ms | 12.770 / 34.185/s | 102.5% | 0.991s | 통과 |
| Raspberry Pi 5 | 100% | 195.771ms | 94.353ms | 6.389 / 20.135/s | 96.6% | 1.772s | 통과 |

Jetson의 75% 조건은 지연 개선이 9.9%여서 사전 고정한 10% gate에 0.1%p 부족했다. 이를
반올림해 통과로 바꾸지 않았다. 모델 크기별 대응 run 결과는 다음과 같다.

| 엣지·프로필 | Server1 지연 우위 | 개별 run gate 통과 | 지연 감소율 중앙값 | 처리량 비율 중앙값 | 양측 sign test |
|---|---:|---:|---:|---:|---:|
| Jetson·약 295만 연산 | 6/12 | 6/12 | 6.6% | 1.214배 | p=1.0 |
| Raspberry Pi·약 295만 연산 | 10/12 | 5/12 | 10.6% | 1.353배 | p=0.0386 |
| Jetson·약 1,180만 연산 | 12/12 | 9/12 | 50.8% | 2.452배 | p=0.000488 |
| Raspberry Pi·약 1,180만 연산 | 12/12 | 12/12 | 48.7% | 3.806배 | p=0.000488 |

약 295만 연산 프로필은 한 지표가 좋아도 부하 전 범위의 지연·처리량 gate가 안정적으로
통과하지 않아 두 엣지 모두 오프로딩 대상으로 채택하지 않는다. 약 1,180만 연산 프로필은
두 엣지 모두 CPU quota 포화 구간에서 Server1 지연 우위가 일관됐고, Raspberry Pi는 선택한
모든 개별 run에서 gate까지 통과했다. 다만 이 비교는 서로 다른 시점에 순차 실행했으므로
노드의 동시 상주 workload와 시간대 네트워크 변동을 완전히 제거한 하드웨어 벤치마크는 아니다.

## 통계 해석

기존 90-run 합성 입력 실험은 서로 다른 부하 조건을 같은 정규분포로 가정하지 않고,
대응된 local/server1 run의 방향만 보는 exact two-sided sign test를 사용했다.

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
| 후보 자격 | 정확한 모델 버전이 엣지 판단 E2E p95 10% 개선·5% 처리량 비열등·오류 0 기준 통과 | 실험별 | 자원 압력과 별개인 전환 gate |

CPU/memory 85%, 300초와 서비스 180초 기준은 보수적인 관찰·debounce 정책이다. 이번 짧은
부하 실험이 이 숫자를 최적 임계값으로 증명한 것은 아니다. 두 압력이 지속돼도 후보 자격이
`rejected`이면 `BLOCKED`로 표시한다. 자격이 `qualified`여도 화면은 `RECOMMENDED` 판단만
제공하며 자동 배포·라우팅·migration을 실행하지 않는다.

이번 실데이터 결과에서 직접 확정할 수 있는 기준은 더 제한적이다. 자연 유입 수준인 1 rps와
가속 재생 50 rps에서 로컬 지연 저하는 관측되지 않았고, 200 rps에서도 로컬은 목표 처리율을
유지했다. 반대로 현재 Server1 경로의 측정 처리 한계는 약 84.4/s였으므로 이 후보를 200 rps
부하의 증강 대상으로 쓰면 안 된다. 따라서 현재 데이터와 모델만으로 “부하가 몇 이상이면
Server1로 전환”하는 양의 임계값은 만들 수 없다. 실제 옥동 모델에서 로컬 p95·backlog 저하가
재현되고 같은 조건에서 후보가 10% 지연 개선과 5% 처리량 비열등을 통과할 때만 전환 임계값을
확정한다. CPU/memory 85%와 지속 시간은 계속 조사 시작용 임시 정책이지 실증 완료 임계값이
아니다.

대표 temporal 모델에 한해서는 다음을 모두 만족하면 Server1 오프로딩 검토가 이득이라는
실험 근거가 있다.

1. 모델 workload가 약 1,180만 element 연산/frame 이상이다.
2. Device1 CPU saturation이 95% 이상이다.
3. 로컬 p95가 95ms 이상이거나 처리량이 12.3/s 이하로 내려간다.
4. 서비스 압력이 기존 debounce 180초 동안 지속된다.
5. 동일 model version의 Server1이 10% 지연 개선·5% 처리량 비열등 gate를 통과한다.

1–3번은 이번 짧은 실험의 교차점에서 얻었고, 4번의 180초는 spike 방지 운영 정책이지 이번
실험이 최적화한 값이 아니다. 이 기준은 `RECOMMENDED`를 만드는 근거이며 자동 전환 승인은
아니다. 실제 옥동 모델이 준비되면 연산량 proxy가 아니라 그 모델 버전의 결과로 교체한다.

Raspberry Pi 5 `etri-dev0003-raspi5`는 같은 대표 모델에 대해 다음 장치별 기준을 사용한다.

1. 모델 workload가 약 1,180만 element 연산/frame 이상이다.
2. Raspberry Pi 실험 Pod의 CPU saturation이 95% 이상이다.
3. 로컬 p95가 90ms 이상이거나 처리량이 20/s 이하로 내려간다.
4. 서비스 압력이 기존 debounce 180초 동안 지속된다.
5. 동일 model version의 Server1이 10% 지연 개선·5% 처리량 비열등 gate를 통과한다.

Raspberry Pi의 90ms·20/s는 이번 고부하 프로필 네 조건에서 관측한 보수적 경계이며 장치
전체나 다른 모델의 일반 임계값이 아니다. 따라서 대시보드는 node name, model version과
workload class가 모두 일치할 때만 이 기준을 사용해야 한다. Jetson과 Raspberry Pi 중 어느 장치도
약 295만 연산 프로필에는 양의 오프로딩 기준을 적용하지 않는다.

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
python3 tools/representative_ai_crossover_experiment.py --help
python3 tools/analyze_representative_ai_platforms.py \
  artifacts/sensor-augmentation/representative-ai-crossover-jetson-20260818.json \
  artifacts/sensor-augmentation/representative-ai-crossover-raspi-20260818.json
kubectl create --dry-run=client --validate=false \
  -f tools/k8s/representative-ai-crossover.yaml -o yaml >/dev/null
kubectl create --dry-run=client --validate=false \
  -f tools/k8s/representative-ai-crossover-raspi.yaml -o yaml >/dev/null
```

원시 JSON은 `artifacts/sensor-augmentation/`의 로컬 실험 증거이며 Git 공개 문서 세트에는
포함하지 않는다. 스크립트, Kubernetes 실험 manifest, 판정기와 이 보고서는 버전 관리한다.
실데이터 요약 증거는
`artifacts/sensor-augmentation/real-data-multirate-20260818.evidence`에 남겼다.
대표 모델 교차점 증거는
`artifacts/sensor-augmentation/representative-ai-crossover-20260818.evidence`에 남겼다.
동일 입력 Jetson·Raspberry Pi 비교의 원시 결과와 분석 결과는 각각
`representative-ai-crossover-jetson-20260818.json`,
`representative-ai-crossover-raspi-20260818.json`,
`representative-ai-platform-comparison-20260818.json`에 남겼다.

다음 승격 시험은 옥동 실제 모델과 입력 계약을 고정한 뒤 30분 이상 endurance, 실제 E2E
수집 주기, network delay/loss/timeout, 요청·응답 payload 크기, GPU utilization·전력, 실패 시
local rollback을 포함한다. 결과 소비자가 엣지인지 중앙인지도 먼저 고정하고 같은 소비 지점까지
측정한다.
후보가 바뀌면 `ServiceDescriptor.augmentation_qualification`을 자동 변경하지 않고 실험
보고서 검토 후 명시적으로 갱신한다.
