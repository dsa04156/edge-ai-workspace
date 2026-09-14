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
