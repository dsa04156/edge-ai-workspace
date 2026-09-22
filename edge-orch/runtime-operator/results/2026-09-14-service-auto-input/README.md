# 서비스 실제 입력 자동 운영 검증

## 결과

- 기존 Llama 서비스의 EdgeX 단건 입력을 자동 정책에 연결하고 `edgex-ai-input` 소비자를 배포했다.
- Device `virtual-temperature-001`, Profile `etri-arduino-temperature`, resource `temperature_raw`의
  새 최신 Reading을 5초 설정으로 확인한다. 실제 간격에는 조회·처리 시간이 추가된다.
- 소비자 실행과 별개로 서비스 UID별 실제 gateway 유입·대기·지연이 자동 전환을 유도한다.
- Nano → Orin → Spark → Orin → Nano 왕복 합격. 증강 사유는 sustained_pressure와
  sustained_latency_breach, 두 복귀 사유는 sustained_low_load_return이다.
- 시험 394건 중391건 성공, 중지 시 미전송3건 취소, 실패·unknown0.
- 같은 검증 구간의 실제 EdgeX 입력64건도 완료/200. SQLite의 총455건은 모두
  해당 경로의 READY 관측·전환 기록 이후에 dispatch됐음을 확인했다.
- 세 노드의 실제 입력 결과를 Core Data 원본 Event의 value·unit·origin·identity와 대조했다.
- 완료 시 Nano Serving, target/retiring0. 이후에도 실제 센서 소비는 계속된다.

## 입력별 측정

기존 8-token 자격과 분리한 센서 요약·최대64-token 입력이다. raw 0/329/1023을
재생한 30초 고정 요청률 시험 결과이며 모든 값·장기 부하·최대 처리량 보장은 아니다.

| 노드 | 입력률 | 성공 | client p95 |
|---|---:|---:|---:|
| Nano | 1.5건/s | 45/45 | 1,909.497ms |
| Orin | 2.2건/s | 66/66 | 547.710ms |
| Spark | 5건/s | 150/150 | 462.089ms |

초기 단일 실제값329의 직렬30건 p95는 각각469.570/326.338/137.117ms였다.
부하와 입력이 달라졌으므로 이 직렬값만으로 최종 정책을 정하지 않았다.
현재 정책은 관측30초·성공표본3개 이상, p95 3,600ms 초과 또는 대기 포화10초 지속,
복귀 p95 2,400ms 이하·후보 입력률80% 이하·대기0과 복귀 조건60초 유지, cooldown60초다.
이는 첫 운용 기준이며 현장 서비스의 확정 SLO가 아니다.

## 검증과 배포 경계

- 배포 소스를 고정한 복사본에서 Operator119개, 기존 EdgeX reader·입력 소비자12개 통과.
- 전체 검사 중 지속 부하100건 시험이 한 번10초 제한을 초과했다. 단독 재실행과 최종
  전체119개 검사는 통과했다. 시험 timeout을 완화하거나 구현을 바꿔 통과시키지 않았다.
- 문서20개 통과, 추진계획140줄 상한 검사1개 실패. 변경 전 HEAD도249줄이어서 기존 실패다.
- `rates-attempt-01.json`: Orin66건이 모델명 불일치로 unknown 처리된 실패 기록이다.
  Nano와 Orin/Spark는 동일 digest를 다른 이름으로 등록하고 있었다. 노드별 alias를
  명시하고 digest 검증을 유지한 뒤 `rates.json`의261/261 성공을 확인했다.
- 왕복 시험 이미지: `192.168.0.56:5000/runtime-operator@sha256:9d8fc6ddf8311f28379b37aca4fba98c0f3684726784e351f42389f6b5bdad58`.
- 시험 뒤 병행 요청 진단 작업의 이미지가 배포됐다. 자동 제어·계약·adapter·demo 모듈
  hash는 같고 API에는 진단 계측이 추가됐다. 현재 이미지와 새 입력 readback은
  `final-verification.json`에 별도로 기록한다. 이 후속 이미지에서 같은 전체 왕복을
  다시 실행한 것으로 보고하지 않는다. 원래 API와 정확한 배포 코드는 `snapshot/`에 있다.
- 후속 관측 중 소비자 입력2건 admission_timeout을 기록했고 다음 입력은 성공했다.
  소비자 관측 ConnectTimeout1회도 있었다. 원인은 확정하지 않았으며 위455건 합격 구간과 합산하지 않는다.

## 남은 경계

최신값 polling이므로 모든 중간 Event 수집·장애 재전송·HA를 보장하지 않는다.
Llama가 raw를 Celsius로 잘못 표현한 원 응답도 보존했다. 문장 품질·단위 변환·현장
이상 판정의 정확도는 검증하지 않았다. 센서 이상감지의 거부된 후보, 합성 HTTP 서비스,
미확보 옥동 모델을 실제 자동 운영 완료 범위에 포함하지 않는다.

`source.json`, `calibration.json`, `rates.json`, `automatic-verified.json`,
`auto-observations.json`, `journal-dispatch-proof.json`, `live-source-readback.json`,
`final-verification.json`이 각 측정 경계의 원본 근거다.
