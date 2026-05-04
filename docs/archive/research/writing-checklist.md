# 논문 작성 체크리스트

## 목적
제출 전에 이 체크리스트를 사용한다.

---

## 1. 문제 정의
- [ ] 문제를 한 문장으로 명확히 썼는가?
- [ ] 왜 정적 배치가 실패하는지 분명히 설명했는가?
- [ ] 왜 mixed-device heterogeneity가 중요한지 보여줬는가?
- [ ] 왜 stage-level orchestration이 필요한지 설명했는가?

## 2. 기여 통제
- [ ] 메인 기여가 3개로 정리되어 있는가?
- [ ] 메인 기여가 runtime orchestration system인가?
- [ ] agent-assisted planning이 분명히 부차적이거나 선택적인가?
- [ ] telemetry, RL, 기타 부가 주제가 중심에서 내려가 있는가?

## 3. 시스템 명확성
- [ ] 아키텍처를 명확한 구성요소로 설명했는가?
- [ ] monitoring, control, data path를 분리해 설명했는가?
- [ ] placement/replanning loop가 분명한가?
- [ ] 노드 역할과 workflow stage가 명확한가?

## 4. 평가 품질
- [ ] 실제 mixed-device testbed가 있는가?
- [ ] 적어도 하나의 강한 실제 workflow가 있는가?
- [ ] 비교군이 충분히 강한가?
- [ ] overload/burst 시나리오가 있는가?
- [ ] orchestration overhead를 측정했는가?
- [ ] ablation study가 있는가?

## 5. claim 통제
- [ ] 모든 claim이 실험으로 직접 뒷받침되는가?
- [ ] marketing 문장을 피했는가?
- [ ] `full agentic system` 같은 표현을 피했는가?
- [ ] Kubernetes나 Prometheus를 대체한다고 주장하지 않는가?

## 6. venue 적합성
- [ ] 제목이 목표 venue와 맞는가?
- [ ] 초록이 venue의 언어와 맞는가?
- [ ] related work가 venue의 독자를 기준으로 정리되어 있는가?

## 7. 최종 sanity check
- [ ] 리뷰어가 논문을 한 문장으로 요약했을 때, 내가 의도한 문장과 같을까?
- [ ] 지배적인 novelty line이 정확히 하나인가?
- [ ] 선택 기능 하나를 빼더라도, 예를 들어 agent-assisted planning을 빼더라도 논문이 여전히 강하게 서는가?
