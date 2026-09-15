# 2026-09-15 범용 모델 실행 연결 검증

Llama 외 실제 이미지 모델을 기존 공통 운영 경로에 연결했다. `digits-classifier`가
Raspberry Pi ARM64와 x86 서버에서 같은 모델 SHA로 숫자 7을 반환했다.

## 실장비 근거

[verification.json](verification.json)에 실행 job 결과, gateway 응답 3건의 모델·요청 identity,
정책 변경에 따른 ARM → x86 → ARM 전환 기록, 종료 시 worker Pod 0개와 Deployment 0 replica를
기록했다. [images.json](images.json)은 배포 이미지 digest와 교체 파일 SHA다.
operator와 aggregator Ready Pod에서 실제 파일 SHA가 게시된 값과 일치함을 확인했다.
Argo aggregator는 Synced/Healthy이며 최종 runtime-services/runtime-demos/nodes HTTP 응답은 200이다.

gateway `/demos/digits-classifier/service`의 start/stop으로 실행을 제어하고,
각 실제 추론은 `/services/digits-classifier/invoke`로 보냈다. 이동 검증은 이 서비스만의
`allowedRoles`/`preferredRole`을 일시 변경한 **정책 지정 전환**이다. 부하에 의한 자동 증강,
장애 주입 또는 처리 중 무손실 전환의 실장비 반복 시험 결과가 아니다.
검증 후 원래 preferred/edge 정책과 `suspended: true`로 복원했다.
새 반복 부하·단건 demo run을 만들지 않았고, gateway 확인 요청은 3건이다.
기존 Llama/quality-api-demo/telemetry-transform-demo의 spec은 변경 전과 완전히 같다.

## 자동 검증과 화면

- 배포 소스 회귀: runtime/resident/demo/common-AI/node controls/AI operations 78개,
  모델 계약·실제 모델 계산·identity 차단·재조회·전환·중지와 latency/후보 판단 검증.
- 마지막 node 버튼 후보 보강 후 model/demo/node controls 30개 통과.
- 커밋 대상 코드만 별도로 구성해 model/runtime/deployment/node controls **53개 통과**.
  기존 별도 작업의 미커밋 common-AI 변경 없이도 새 계약과 CRD가 동작한다.
- aggregator 공통 projection 12개, 기존 JS 범위 35개 통과. 마지막 preferred 표시 보강 후
  common-runtime/execution-map/placement-overview 25개 및 새 preferred 표시 시험 통과.
- 실제 브라우저 1440×1100, 390×844에서 서비스 선택·맵 2개 노드·실행/중지·노드 부하 버튼과
  가로 넘침 없음 확인. 실행 중에는 현재 Raspberry Pi의 부하 시작만 활성화,
  중지 뒤 서비스 실행만 활성화된다. 선택은 새로고침 후 유지됐다.
- 배포 교체 중 기존 단일 replica 구조의 503이 일시 관측됐고, 배포 종료 뒤 조회 200과
  최신 관측을 재확인했다. 이를 무중단 배포 결과로 설명하지 않는다.

## 남은 범위

`verifiedNodes`는 실행 호환성만 뜻한다. 처리율/p95 자격, 여러 서비스 동시 자원 경쟁,
일반 AI의 부하 증강·저부하 복귀 및 실제 장기 부하 제거 시험은 후속이다.
새 `modelRuntime`에는 자동 모드를 계약에서 차단하고 화면에 미활성으로 표시한다.
문서의 전체 범용화 인수 기준은 [설계안](../../../../docs/전체-AI-서비스-자동-배치-설계안.md)을 따른다.
사용 절차와 학습 출처는 [서비스 안내](../../examples/digits-model/README.md)에 있다.
