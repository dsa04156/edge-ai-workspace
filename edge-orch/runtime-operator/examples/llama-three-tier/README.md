# Llama 3단계 자동 운영 데모

운영자 소유의 고정 resident runtime 및 RuntimeService 계약이다. 동적 Pod 명세 입력 도구가 아니다.

- Nano: 기존 llama-nano API + 별도11436 GPU runtime/PVC. 기존 실험용11435 프로세스·캐시는 유지한다.
- Orin/Spark: 기존 llama-agx/llama-spark resident Pod를 재사용한다.
- 순서: Nano → Orin → Spark, 자동 증강. 저부하·무부하 복귀는 역순 자동 정책이다.
- runtime-operator의 stages 지원 이미지와 k8s/crd.yaml을 먼저 반영한 뒤 nano-runtime.json과 service.json을 적용한다.
- 대시보드 배포 소유자는 기존 Argo CD edge-orch-state-aggregator다.
- Nano 측정 및 실제 반영 근거는 ../../results/2026-09-11-three-tier/에 저장한다.
- 2026-09-14 최신 사용자 요구로 `approvalRequired: false`를 적용한다. 부하 시작/제거로 자동 왕복을 시험한다.
- 과거 승인 방식의 시험 근거와 현재 자동 방식의 근거는 날짜별 results 경로로 구분한다.

현재 노드의 부하 버튼으로 시작한 시험은 Nano → Orin → Spark 이동 후에도 계속된다.
제거 버튼은 현재 실행 노드에 표시되며, 제거 시 서비스는 실행 상태를 유지한다.
중복된 AI `서비스 부하 시작` 버튼은 제공하지 않는다.

정책값은 대기 지속 또는 p95 초과 10초, 복귀 유지 60초, 전환 후 대기 60초다.
20초 전체 유입률이 하위 검증 요청률의 80% 이하이고 저부하·지연 회복 또는 무부하가
60초 유지될 때 한 단계씩 복귀한다. 무부하 표본을 지연 회복 성공으로 표현하지 않는다.
실제 응답 확인과 부하 제거 후 역순 복귀까지 시험하며 상세 근거는
`../../results/2026-09-14-load-policy/`를 따른다.
