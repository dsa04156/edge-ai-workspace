# 운영 진입점

## 한 줄 요약

운영자는 현재 데모 runbook에서 시작하고, dashboard 검증과 E2E 검증 문서로 실제 관찰 가능한 데모 경로를 확인한다.

## 현재 기준

운영 문서는 개념 문서와 분리한다.
실행, 검증, 장애 원인 좁히기 질문은 Ops 문서에서 시작한다.

| 상황 | 시작 문서 |
|---|---|
| 현재 데모 실행 | [현재 데모 Runbook](../ops/runbook-current-demo.md) |
| dashboard 동작 확인 | [Dashboard 검증](../ops/dashboard-verification.md) |
| end-to-end 데모 확인 | [E2E 데모 검증](../ops/e2e-demo-verification.md) |
| pod 또는 network 경로 점검 | [네트워크 트러블슈팅](../ops/troubleshooting-network.md), [파드 통신 점검](../ops/pod-connectivity-check.md) |
| edge node join 확인 | [Edge 노드 조인 점검](../ops/edge-node-join-check.md) |
| GPU runtime 맥락 확인 | [HAMi GPU runtime](../ops/gpu-hami-runtime.md) |

## 운영자 읽기 순서

라이브 데모에서는 다음 순서로 본다.

1. 현재 데모 runbook을 읽는다.
2. node와 mapper 상태를 확인한다.
3. 올바른 node에서 test publisher를 실행하거나 상태를 확인한다.
4. dashboard device row와 service binding을 본다.
5. freshness와 `DeviceStatus`를 별도 신호로 확인한다.
6. 기술 상태가 보인 뒤 KPI 문서를 사용한다.

## 경계

Ops 문서는 operator assistant나 workflow designer가 infrastructure를 변경할 수 있는 것처럼 표현하지 않는다.
별도 승인된 control path가 생기기 전까지 agent 보조는 read-only 요약과 troubleshooting 안내로 제한한다.

## 관련 Wiki

- [현재 데모 흐름](current-demo-flow.md)
- [상태와 텔레메트리](status-and-telemetry.md)
- [대시보드와 KPI 모델](dashboard-and-kpi.md)

## 근거 문서

- [현재 데모 Runbook](../ops/runbook-current-demo.md)
- [Dashboard 검증](../ops/dashboard-verification.md)
- [E2E 데모 검증](../ops/e2e-demo-verification.md)
- [Kagenti 운영 보조](../kagenti-operator-assistant.md)
