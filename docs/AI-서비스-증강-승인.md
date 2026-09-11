# AI 서비스 증강 승인

AI 추론이 밀리면 더 여유 있는 장비를 추천한다. 운영자가 승인하면 모델을 준비하고
새 요청의 처리 위치를 변경한다. 센서 수집과 장비 연결은 유지한다.

첫 범위는 공통 제어기의 `llama-inference`다. 모델·입력·후보는 기존 Kubernetes 계약을
따르고 NEXUS에서 임의 노드·image·command를 받지 않는다. 부하 시험은 등록된 입력과 동시성 제한을 사용한다. 노드별 부하는 제거 또는 실행 노드 변경까지
유지하고, 기존 전체 경로 시험은 최대 요청 수·시간 제한을 유지한다. 합성 HTTP fixture는 AI 서비스로 표시하지 않는다.

서비스별 집계는 gateway의 실제 완료 요청 지연과 실패, 대기·진행 요청을 사용한다.
CPU/GPU 노드 사용률과 모델 메모리는 보조 정보이며 서비스별 추론 처리율과 구분한다.
관측 실패·오래된 표본은 0이나 정상으로 표시하지 않는다.

`policy.approvalRequired=true`인 AI 서비스의 부하 증가·지연 초과 추천은 원장에 저장한다.
승인 요청은 최신 서비스 UID·추천 ID와 자격을 다시 검사한다. 중복 승인은 같은 결과를
조회하며 재시작 후 미실행 승인은 폐기한다. 준비 실패와 실제 전환 완료를 구분한다.
저부하 복귀·drain은 기존 서비스 정책에 따른다. 추론 활성화와 신규 요청 전환이 증강의
실행 범위이며, Pod/GPU 예약 개수 증가나 진행 중 계산 상태 이동을 뜻하지 않는다.

> 2026-09-11 16:40 KST 운영 반영 완료. 노드별 부하는 제거 또는 실행 노드 변경까지 유지한다.

## 사용 순서

1. NEXUS `자원·오프로딩`의 AI 추론 카드를 연다. `AI 서비스 → 클러스터 실행`에서도 같다.
2. `서비스 실행` 후 현재 실행 중인 노드의 `Nano에 부하 주기`를 누른다.
   고정 입력을 동시 6건으로 반복하며, 부하 제거 또는 실행 노드 변경까지 유지한다.
3. 부하가 지속되면 추천 노드와 검증 처리율·지연을 확인하고 `추천 노드 증강 승인`을 누른다.
   추천 조건이 사라지거나 대상이 바뀌면 이전 승인은 실행되지 않는다.
4. `승인 접수` → `모델 준비 중` → `증강 적용 · 신규 요청 경로 전환 완료`를 확인한다.
   Nano 부하는 경로 변경으로 종료된다. Orin에서 계속 부하를 주려면 `Orin에 부하 주기`를 누른다.
   해당 노드의 `부하 제거`는 새 요청 생성을 멈추고 이미 처리 중인 요청을 마무리한다.
   부하 제거 후에는 기존 저부하 복귀 정책이 적용될 수 있다.

## 측정과 추천 기준

- 유입·완료 처리율은 현재 실행체 기준 gateway 요청의 최근 20초 집계다. 실제 요청의
  입력 길이·출력 토큰에 따라 달라지므로 장비의 절대 최대 성능으로 해석하지 않는다.
- 검증 수용 요청률은 Git 계약의 동일 8-token 입력 시험값이다: AGX 4.8건/s,
  Spark 6건/s. 두 실행체의 동시 처리 한도는 각각 1건이다.
- 대기와 진행 요청을 합친 사용 비율이 0.8 이상 4초 지속되거나, 유효한 성공 표본
  10건 이상에서 p95가 900ms를 4초 넘으면 자격을 만족하는 더 큰/빠른 후보를 추천한다.
- 후보의 Ready·pressure·아키텍처·resident 모델 binding·검증 지연을 검사한다.
  GPU/CPU 사용률만으로 새로운 호환 모델이나 처리 용량을 추정하지 않는다.
- 추천은 60초 유효하며 승인 시 다시 관측한다. 실패/표본 부족은 지연 정상 판정이 아니다.
  최초 배치·장애 대응과 저부하 복귀는 기존 정책을 유지한다.

## 검증과 배포 근거 (2026-09-11)

- 공통 제어기 Python 시험 66건 통과: 승인 전 실행 차단, 정확한 추천 승인과 적용,
  중복 승인, 부하·후보·세대·UID·유효기간 변경, 재시작, 제한 부하와 재접수 포함.
- 대시보드 Python 전체 시험에서 421건 통과. 별도 기존 virtual-device-runtime fixture가
  Git worktree에 없어 실패한 연동 시험 1건은 기존 로컬 fixture를 임시 연결해 재실행 통과했다.
- 대시보드 JavaScript 전체 256건 통과. 최종 안내 문구 수정 후 관련 9건 재실행 통과.
- Playwright 모의 API로 부하 버튼 → 추천 표시 → 승인 → 적용 표시를 확인했다.
  데스크톱 1440px와 모바일 390px 화면을 확인했고 모바일 가로 넘침은 없었다.
- 두 Kustomize 렌더링과 CRD 서버 dry-run을 통과했다. 배포는 기존 운영 image를 기반으로
  이번 변경 파일만 추가한 불변 digest를 사용한다. 원래 작업 디렉터리의 미커밋 변경은
  배포 소스와 섞지 않으며, 변경된 파일 hash와 base digest를 별도 근거로 보관한다.
- 실장비 부하 시험과 증강 승인은 아직 실행하지 않았다. 운영자의 버튼 클릭 결과를
  이번 모의 API 검증 결과와 구분해서 기록해야 한다.


운영 반영 확인: Argo CD `edge-orch-state-aggregator`가 구현 커밋 `97e9397d`에서
Synced/Healthy였고, 대시보드와 runtime-operator의 Ready Pod imageID가
[이미지 근거](../edge-orch/runtime-operator/results/2026-09-11-augmentation/images.json)의
배포 digest와 일치했다. 변경한 정적 파일의 HTTP 응답 SHA256도 소스와 일치한다.
실제 대시보드에서 AI 카드 1개, 부하 버튼 활성, 부하가 없는 동안 승인 버튼 비활성,
브라우저 오류 0건을 확인했다. 상세 관측은
[운영 검증](../edge-orch/runtime-operator/results/2026-09-11-augmentation/live-verification.json)에 보관한다.

## 실행 지도와 진행 피드백 (2026-09-11 후속 개선)

지표·노드 지도·부하 시험·중단·증강 승인을 하나의 작업 영역에서 확인한다.
왼쪽은 요청 입구에서 실제 처리 노드로 향하는 경로, 오른쪽은 실행 제어다.
노드를 선택하면 실행체·모델 메모리·동시 처리 한도를 펼치며 자동 갱신 중 선택과
키보드 focus를 유지한다. 전체 서비스 진단과 긴 시험 이력은 아래 접힌 상세에 둔다.

- 버튼 클릭 즉시 시작 접수/중단 접수/승인 접수 로딩을 표시한다.
- 부하 시험은 기준 부하·집중 부하·저부하 단계, 경과 초, 전송·성공·실패·미확인
  건수를 표시한다. 완료율을 산정할 근거가 없어 임의 백분율은 표시하지 않는다.
- 요청 대기와 실제 AI 처리, 추천 승인 대기, 모델 준비, 이전 요청 마무리,
  적용 완료를 구분한다. Ready 상태만으로 `추론 실행 중`이라고 표시하지 않는다.
- 지도는 제어기의 자격 후보·현재·준비·반환 노드만 사용한다. 후보의 모델 준비 여부를
  추정하지 않는다. 현재 관측된 대기/진행 요청이 있을 때만 요청 경로를 움직인다.
- 데이터 조회 실패/오래된 관측은 실행 확인 불가로 표시하고 요청 경로 애니메이션과
  승인·부하 동작을 비활성화한다. 모션 줄이기 설정에서는 이동 애니메이션을 끈다.

검증: JavaScript 258건, 관련 Python API 8건 통과. 모의 브라우저에서 시작 접수,
집중 부하·중단, 승인 후 준비·적용, 조회 실패 시 애니메이션 0개, 갱신 후 노드 선택과
focus 유지, 모바일 390px 가로 넘침 없음 확인. 이 UI 변경의 검증에서는 실제 부하와
실제 증강 승인을 호출하지 않았다.

후속 운영 배포 `5297a142`에서 Argo Synced/Healthy, 응답 중인 Ready Pod의 imageID와
변경 정적 파일 hash 일치를 확인했다. 실제 화면에서 AGX·Spark 노드 2개, 무부하의
`요청 대기 중`, 1440×900 한 화면 배치, 브라우저 오류 0건과 390px 가로 넘침 없음도
확인했다. [후속 검증 기록](../edge-orch/runtime-operator/results/2026-09-11-augmentation/interactive-map-verification.json).

## 부하 제거와 노드 지표

`AI 추론 부하 주기` 옆에 `부하 제거` 버튼을 항상 표시한다. 실행 중인 정확한 시험
UID/실행 ID로 기존 중단 API를 호출하며, 접수 → 남은 요청 마무리 → 부하 제거 완료를
구분한다. 대기·완료 상태에서는 버튼을 비활성화한다. AI 서비스 자체 종료나 모델 메모리
해제 명령이 아니라 시험 요청 발생을 중단하는 동작이다.

AGX·Spark 지도 카드에 노드 전체 CPU·메모리·GPU 사용률과 원 수집 시각을 표시한다.
`/state/nodes`의 Prometheus 관측을 재사용하며 AI 서비스 요청 지표와 분리한다.
수집 60초 초과, exporter down, 조회 실패는 측정 불가다. GPU 필드가 없는 노드는
`미수집`으로 표시하고 0%로 대체하지 않는다. 노드 상세에는 수집된 GPU 메모리·온도도
표시한다. 현재 Spark GPU 사용률은 기존 수집 경로에 값이 없으므로 미수집 상태다.

검증: JavaScript 전체 260건, 최종 관련 13건 통과. 모의 브라우저에서 부하 시작 후
제거 접수 → 제거 완료와 버튼 비활성 전환을 확인했다. 운영 배포 `03748ea7`에서
Argo Synced/Healthy, Ready imageID와 변경 정적 파일 hash 일치, 실제 노드 지표와
상시 부하 제거 버튼, console 오류 0건을 확인했다. 상세는
[부하 제거·노드 지표 검증](../edge-orch/runtime-operator/results/2026-09-11-augmentation/hardware-and-stop-verification.json).


## 지도 온도 표시 (2026-09-11)

노드 사용률 아래에서 CPU·GPU·시스템 온도를 °C로 확인한다. `/state/nodes`의 최신 Prometheus 실측을 사용하며, 수집되지 않은 센서는 `미수집`, 조회 실패·exporter down·60초가 지난 관측은 `—`로 표시한다. 온도는 관측 정보이며 증강 승인 조건이나 노드 건강 판단 임계값을 변경하지 않는다.

- CPU: coretemp/k10temp/zenpower hwmon 또는 `cpu-thermal`/`x86_pkg_temp` thermal zone의 최댓값. NVMe·Wi-Fi·ACPI 값을 CPU 온도로 대체하지 않는다.
- GPU: DCGM 또는 `gpu-thermal` thermal zone의 최댓값. 동일 노드에 여러 관측 주소가 있으면 최댓값으로 합친다.
- 시스템: `acpitz` thermal zone의 최댓값. CPU나 GPU 접합 온도와 구분한다.
- AGX에서 CPU·GPU thermal zone, Spark에서 ACPI 시스템 온도를 확인했다. Spark CPU·GPU 온도는 현재 수집 경로에 없으므로 `미수집`이다. 센서별 수집이 끊긴 주기에도 값을 채워 넣지 않는다.

검증: Python 19건과 JavaScript 14건 통과. 운영 Argo Synced/Healthy, Ready Pod의 5개 변경 파일 및 정적 HTTP 해시 일치를 확인했다. 실제 브라우저에서 온도 2행, 390px 가로 넘침 없음, 콘솔 오류 0건을 확인했다. 최종 API 표본은 AGX CPU 42.656°C, Spark 시스템 39.3°C였다. AGX GPU thermal 값은 사전 조회에서 관측됐으나 최종 표본에서는 빠져 `미수집`으로 표시했다. 이 검증에서 실제 부하 시작이나 증강 승인을 호출하지 않았다. 상세 근거: `edge-orch/runtime-operator/results/2026-09-11-augmentation/temperature-verification.json`.


### 노드 상태와 GPU 미수집 원인 확인

자원·오프로딩의 `노드 상태`에도 같은 CPU·GPU·시스템 온도를 표시한다. 최신 수집 실패나 60초 초과 표본은 온도를 숨기며, `미수집`만으로 수집기 미설치를 단정하지 않는다.

2026-09-11 15:13 KST 읽기 전용 진단:

- AGX: node-exporter와 jetson-gpu-exporter가 배포되어 있고 Prometheus up=1. Jetson 전용 exporter는 GPU 사용률만 수집한다. 온도는 node-exporter의 thermal zone 경로다. 기존 read-only sysfs mount에서 CPU temp는 42562 m°C, GPU temp 파일은 `No data available`을 반환했다. 센서 파일이 존재하지만 그 시점 읽기는 실패한다. 원인이 전력 상태 때문인지는 이번 진단으로 확정하지 않았다.
- Spark: NVIDIA GB10 드라이버와 추론 runtime은 동작하며 기존 추론 컨테이너의 `nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu --format=csv,noheader`는 `NVIDIA GB10, 37, 0 %`를 반환했다. GPU 온도 자체는 읽을 수 있다. 그러나 DCGM DaemonSet이 amd64 + gpu.platform=server 노드만 선택해 arm64 Spark에는 GPU exporter가 배포되지 않았다. GPU 사용률·온도를 지속 표시하려면 Spark에 맞는 수집기와 Prometheus scrape 연결이 필요하다. 이번 변경에는 설치를 포함하지 않는다.
- 서버 1·2: DCGM exporter가 배포되어 Prometheus up=1. Spark의 미수집을 전체 GPU 수집기 미설치로 일반화하지 않는다.


## Nano → Orin → Spark 3단계 승인 증강

2026-09-11 사용자 요청으로 기존 두 후보를 다음 세 단계로 확대한다.

| 단계 | 실제 장비 / 노드 | 검증 수용 요청률 |
| --- | --- | --- |
| 1 Nano | Jetson Orin Nano / etri-dev0001-jetorn | 2건/s |
| 2 Orin | Jetson AGX Orin / etri-dev0005-jetagx | 4.8건/s |
| 3 Spark | DGX Spark GB10 / etri-ser0003-cg0ms0 | 6건/s |

`policy.stages`가 variant 순서를 선언한다. 단계의 qualifiedRps는 순서대로 증가해야 한다. 부하·지연 위반 때 바로 다음 단계만 추천하고 매번 새로운 승인 ID를 요구한다. Orin이 부적격이면 Nano에서 Spark로 건너뛰어 부하 증강하지 않는다. 현재 실행 장애·초기 배치는 가용 후보 복구 정책을 별도 사유로 사용한다. 저부하와 충분한 회복 지연 표본이 있으면 Spark → Orin → Nano 순으로 자동 복귀한다. 같은 edge 역할인 Nano·Orin도 서로 다른 단계로 처리한다. 시험 시작 전 기준 단계도 edge 역할 전체가 아니라 Nano다.

지도에는 1·2·3단계, 장비명, 실제 hostname, 검증 요청률/p95, CPU·메모리·GPU 및 온도를 함께 표시한다. 화살표는 증강 순서이며 강조 노드가 실제 요청 경로다. 3단계에서도 부하 제거 버튼과 승인별 접수·준비 상태를 유지한다.

Nano는 `llama-continuity-test/llama-nano`에 별도 GPU 예약 resident container와 4Gi PVC를 추가했다. 포트11436을 사용해 기존 실험용11435 runtime과 분리하며 기존 실험 모델 캐시를 삭제하지 않는다. 임의 hostPath를 추가하지 않고 기존 NVIDIA runtime/device plugin을 사용한다. `CONTINUITY_SOURCE`의 해제 금지를 제거해 현재 제어기의 deactivate 계약을 따른다. 동일 model digest `baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878`와 동일8-token 입력을 사용한다. GPU17/17layers offload, 모델 VRAM1348.45MiB, 초당2건20개+워밍업2개 성공을 확인했다. 2건/s는 이번에 검증한 운용점이며 장비의 최대 성능을 뜻하지 않는다. 직접 worker p95는267.232ms이며 기존 gateway/port-forward 경계 수치와 최대 성능 비교를 하지 않는다. 부하/지연 판단은 계속 실제 gateway queue+response 집계를 사용한다.

계약과 Nano 배포: `edge-orch/runtime-operator/examples/llama-three-tier/`. 실측 원본: `edge-orch/runtime-operator/results/2026-09-11-three-tier/nano-qualification.json`. 승인 두 번·단계별 복귀·중간 단계 부적격·동일 역할 복귀는 자동시험으로 검증하며, 운영 증강 승인 클릭은 사용자에게 남긴다.

운영 반영 검증: Nano gateway 시험도 초당2건20개 성공(p95 861.485ms, 900ms 기준 이내), 저부하 직렬20개 성공(p95 701.935ms)을 확인했다. Nano의 qualifiedP95는 worker 직접267ms 대신 이 gateway 직렬값701.935ms를 사용한다. 이를 반영해 3단계 계약의 저부하 복귀 지연 기준을700→750ms로 조정하고 증강 지연 기준900ms와 시간 hysteresis는 유지한다. GPU warmup2개씩과 gateway smoke3개는 각 시험에서 별도 기록했다.

제어기71건·API9건·UI15건 통과. 실제 운영에서 두 새 이미지의 Ready Pod/파일 해시, ArgoSyncedHealthy, Nano ACTIVE와 Orin/Spark CACHED, 세 후보 eligible, 센서 Device Service2개 Ready, desktop3단계 표시와390px 넘침 없음·콘솔 오류0을 확인했다. 실장비의 두 단계 증강 승인 클릭은 사용자에게 남겼으며 실제 3단계 승인 왕복 완료를 주장하지 않는다. 현재 설정 및 실측 근거는 `results/2026-09-11-three-tier/live-verification.json`과 같은 디렉터리의 gateway/return qualification 파일이다.


## 서비스 실행과 노드별 부하 제어 (2026-09-11 사용자 후속 승인)

서비스 실행·중지와 시험 부하 시작·제거를 구분한다. 사용자가 현재 Llama 실행 노드에
부하를 주고 승인으로 Orin에 이동한 뒤 Orin 부하 버튼을 사용하는 흐름을 선택했다.

- 서비스 실행: RuntimeService의 `suspended=false`를 저장하고 모델 준비 후 요청 대기.
- 서비스 중지: `suspended=true`를 저장하고 모든 시험 요청 생성을 중지한다. 대기 요청은
  dispatch 전에 취소하고 이미 dispatch한 요청은 마무리한 뒤 기존 drain으로 모델을 해제한다.
  중지 완료 확인 전 재시작은 거부한다. resident 관리 Pod·모델 cache·GPU 예약은 유지한다.
- Nano·Orin·Spark 카드마다 부하 주기/부하 제거 버튼을 항상 표시한다. 시작은 최신 관측에서
  해당 노드가 현재 서비스 경로이고 안정된 상태일 때만 허용한다. 비활성 이유를 카드에 표시한다.
- `node-load`는 기존 고정 Llama payload와 동시성 상한을 사용하고 부하 제거까지 반복한다.
  기존 40초·512건 자동 종료는 적용하지 않는다. 완료 요청 목록은 최근 64건과 모든 미완료 건만
  유지하며 개별 dispatch 원장과 전체 집계는 보존한다. 임의 prompt,
  endpoint, CPU/GPU stress command는 입력받지 않는다. 기존 전체 경로 부하와 달리 baseline·
  recovery 요청을 추가하지 않고 선택 노드에서만 압력을 가한다.
- 실행 노드가 바뀌면 해당 시험을 끝내고 대기 요청을 새 노드로 넘기지 않는다. Orin의 새로운
  부하는 사용자가 Orin 버튼을 클릭해 시작한다. 증강 승인은 별도 클릭을 유지한다.
- 부하 제거는 exact service UID/run ID로 동작하며 서비스 실행 상태는 유지한다. 대기 취소는
  실패와 별도 집계한다. 동일 실행 ID 재전송은 새 시험을 만들지 않는다.
- 동일 노드 재시험 간격은 10초이며 화면에 남은 시간을 표시한다. 프로세스 재시작 시 시험은
  자동 재실행하지 않고 Interrupted로 기록한다.

`runtime-operator`가 기존 namespace의 RuntimeService get/update 권한으로 실행 상태를 저장한다.
최신 UID/resourceVersion을 검증하고 `spec.suspended`만 바꾼다. API는 demo opt-in과
approvalRequired AI 계약으로 한정한다. 대시보드는 기존 same-origin·JSON·X-Runtime-Demo
제약의 proxy이며 Kubernetes 권한을 새로 추가하지 않는다. 센서 수집과 서비스 설계 dry-run은
이번 제어와 별개다. 검증은 `tests/test_node_controls.py`, proxy/UI 회귀와 운영 재현 근거를 따른다.

### 위 버튼의 운영 검증 (2026-09-11 16:21 KST)

- 서비스 실행/중지와 각 노드 부하/제거 버튼을 운영 대시보드에 배포했다.
- 실제 Nano 부하 버튼→제거: 전송70, 성공65, dispatch 전 취소5, 실패0, 미확인0.
  `Stopped`, 서비스 실행 유지. 제거 후 새 요청이 계속 발생하지 않음을 원장으로 확인했다.
- 실제 서비스 중지: `Suspended`, serving=false, retiring=[], 모델 메모리0MiB.
  15초 이상 중지 후에도 최신 중지 관측과 시작 버튼을 유지한다.
- 재실행: Nano ACTIVE, 모델1348.45MiB, 단일 추론1/1성공(원장 경과 약421ms).
- operator75, aggregator API10, UI17 =102개 테스트 통과. UID 충돌/타깃 변경,
  대기 취소, 모델 drain/재시작, 동일 ID 및 노드 경계와 기존 증강 승인을 회귀 검증했다.
- 1440px·390px 화면과 실제 클릭, 가로 넘침 없음·중첩 버튼0·콘솔 오류0 확인.
  두 운영 이미지/소스 해시 일치, 대시보드 Argo Synced/Healthy, EdgeX 센서2Pod Ready 유지.
- Orin으로 실제 증강 승인 클릭은 이번 검증에서 수행하지 않았다. 경로 변경 후 기존 노드
  부하가 새 노드에 전달되지 않는 조건은 단위시험에서 검증했다.
- 근거: `edge-orch/runtime-operator/results/2026-09-11-node-controls/`.

### 노드 부하 자동 종료 수정 (2026-09-11)

최근 두 실행은 약 42.69초·41.53초에 종료됐다. 기존 `pressureSeconds=40`이 노드별
부하에도 적용된 것이 원인이다. `node-load`의 시간·총 요청 종료 조건을 제거하고 수동 제거,
서비스 중지, 실행 노드 변경과 관측·계약 검증 실패 시 종료는 유지했다.

- operator 관련21개, UI8개 테스트 통과. 새 회귀 시험은 1초·2건 설정에서 100건 이상
  계속 실행, 최근 요청 목록 크기 제한, 수동 제거 후 요청 증가 없음과 서비스 실행 유지를 확인한다.
- 원래 전체 경로 시험의 시간·요청 제한은 유지한다.
- 최초 배포는 저장소 연결 거부로 중단됐다. 이후 사용자 승인으로 기존 fstab의 데이터 디스크를
  `/mnt/data3tb`에 다시 마운트하고 기존 registry 컨테이너를 실행해 복구했다.
- 두 수정 이미지의 운영 Ready/source hash 일치 및 Argo Synced/Healthy를 확인했다.
- 실제 Nano 버튼 클릭 후 48.6초에도 Running/pressure, 전송145건을 관측했다. 제거 버튼 클릭 후
  Stopped/finished, 최종150건(성공140·실패5·dispatch 전 취소5·미확인0),
  이후 요청 수150건 유지와 서비스 Running을 확인했다. 실패5건 원인은 이번 수정의 검증 범위가 아니다.
- 증강 승인 버튼은 누르지 않았다. 운영 센서2Pod Ready와 브라우저 콘솔 오류0을 확인했다.
- 근거: `edge-orch/runtime-operator/results/2026-09-11-manual-node-load/`의 진단·이미지·운영 원장·검증 파일.

### 관측 상태 반복 표시 수정 (2026-09-11)

운영자가 정상과 `관측 연결 확인 중`이 반복된다고 보고했다. 조사 중 서버를 5초 간격으로
7회 관측한 결과 모두 Serving/오류 없음, 서비스 관측 나이 약0.65~1.34초였다.
사용자 PC 시각은 직접 측정하지 않았으므로 실제 반복의 유일한 원인이라고 단정하지 않는다.

브라우저가 서버 timestamp를 로컬 `Date.now()`와 직접 비교해 새 응답을 미래 또는 오래된
값으로 판정하는 결함을 재현했다. 응답의 서버 시각과 `performance.now()` 경과시간을
사용하도록 수정해 PC 시계 차이·변경에 독립적으로 15초 관측 만료를 판단한다.
노드 지표의 수신 경과시간도 같은 단조 시계를 사용한다. 실제 서비스 관측이 오래됐거나
API 오류가 있으면 제어를 비활성화하고 원인·마지막 관측 시각·5초 재시도를 표시한다.
서버 측 관측/승인 검증과 서비스 실행 정책은 변경하지 않는다.

관련 JS20개 테스트 통과: 시계 앞뒤 차이·변경에도 정상 유지, 경과15초 초과 시 만료,
실제 stale/조회 오류 표시와 기존 서비스·노드 제어 회귀를 확인했다.
근거: `edge-orch/runtime-operator/results/2026-09-11-observation-clock/`.

관측 API가 오류와 빈 목록을 반환해도 직전 서비스 지도는 유지하며 마지막 확인 상태로 표시한다.
서비스가 삭제됐다는 정상 응답의 빈 목록과 구분한다. 다음 정상 폴링에서 오류를 해제한다.
이 경로도 회귀 시험에 포함한다.

배포 후 기존 브라우저 문맥이 이전 runtime JS를 실행하는 상태도 발견했다. 두 runtime JS의
script URL에 파일 SHA-256 기반 버전을 붙여 문서가 갱신될 때 기존 스크립트 캐시와 분리한다.
