# Kagenti 운영 보조 Agent PoC

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC에 Kagenti 계열 agent를 붙일 때의 최소 구현 범위를 정리한다.

현재 PoC에서 Kagenti는 자율 제어 계층이 아니라 운영자 보조 계층으로 둔다.
역할은 `state-aggregator`가 만든 운영 상태를 읽고, 한국어로 요약하며, 운영자가 먼저 확인할 대상을 제안하는 것이다.

## 한 줄 정의

```text
Kagenti operator assistant = state-aggregator API를 읽어 한국어 운영 요약과 점검 순서를 제공하는 read-only agent PoC
```

## 현재 구현 위치

state-aggregator에 Kagenti 연동용 read-only endpoint를 추가했다.

```text
GET /state/operator-assistant
```

이 endpoint는 내부적으로 현재 dashboard 상태를 기반으로 운영자 요약 payload를 만든다.

참조하는 기존 API:

```text
/state/dashboard
/state/devices
/state/nodes
/state/summary
```

## 응답 구조

`/state/operator-assistant` 응답은 다음 구조다.

```text
generated_at
assistant_name
mode
summary_ko
focus_devices[]
recommended_actions[]
guardrails[]
source_endpoints[]
```

예시 의미:

| field | 의미 |
|---|---|
| `assistant_name` | PoC agent 이름. 현재 `kagenti-operator-assistant-poc` |
| `mode` | 현재는 `read_only` 고정 |
| `summary_ko` | 한국어 운영 요약 |
| `focus_devices[]` | degraded/unavailable device 중 우선 확인 대상 |
| `recommended_actions[]` | 운영자가 확인할 점검 순서 |
| `guardrails[]` | agent가 하면 안 되는 일 |
| `source_endpoints[]` | 요약의 기준이 되는 state API |

## 운영자 요약 예시

```text
Kagenti 연동 PoC용 read-only 운영 보조 요약입니다.
등록 device 31개 중 live device 24개,
서비스 데모 연결 device 28개,
우선 점검 대상 3개입니다.
telemetry configured 비율은 0.903이고, telemetry freshness 비율은 0.774입니다.
```

## focus device 예시

```json
{
  "name": "vib-device-01",
  "node_name": "etri-dev0001-jetorn",
  "status": "degraded",
  "reason": "telemetry and DeviceStatus stale",
  "service_demo_group": "설비 상태 모니터링",
  "telemetry_fresh": false,
  "device_status_fresh": false,
  "mapper_running": true,
  "node_ready": true
}
```

## recommended action 예시

```text
vib-device-01: publisher 실행 위치, DEVICE_PLAN/DEVICE_FILTER, local mosquitto, InfluxDB latest telemetry를 확인한다.
```

이 문구는 운영자가 먼저 확인할 경로를 좁히기 위한 것이다.
agent가 직접 재배포, 삭제, 제어 명령을 실행한다는 의미가 아니다.

## Guardrail

현재 PoC에서 agent가 하면 안 되는 일은 다음이다.

- Kubernetes 리소스 수정
- Device CR 수정
- mapper 재배포
- `kubectl delete`, `kubectl apply`, `kubectl rollout restart` 실행
- MQTT command topic publish
- actuator command 직접 실행
- placement/offloading/workflow 판단
- LLM 기반 전역 제어

허용하는 범위는 다음이다.

- state-aggregator API 조회
- dashboard KPI 요약
- degraded/unavailable device 목록화
- runbook 기반 점검 순서 제안
- 서비스 데모 그룹과 KPI 의미 설명

## 우리 PoC에서의 위치

현재 운영 흐름은 다음이다.

```text
Device
  -> MQTT telemetry / command
  -> mqttvirtual mapper
  -> InfluxDB raw telemetry
  -> KubeEdge DeviceStatus snapshot
  -> state-aggregator
  -> dashboard
  -> operator assistant endpoint
  -> Kagenti agent / 운영자 요약
```

Kagenti agent는 `state-aggregator` 뒤에 붙는 운영 보조 layer다.
디바이스-서비스 연결 구조와 통합 운영 가시화를 설명하는 데 사용한다.

## 데모 시나리오

1. 운영자가 dashboard를 연다.
2. `state-aggregator`가 device/node/telemetry/status/service binding 상태를 보여준다.
3. Kagenti agent가 `/state/operator-assistant`를 조회한다.
4. agent가 한국어로 현재 상태를 요약한다.
5. degraded/unavailable device가 있으면 `focus_devices[]`와 `recommended_actions[]`를 보여준다.
6. 운영자는 추천 순서에 따라 publisher, local mosquitto, mapper, node, DeviceStatus 경로를 확인한다.

## 발표/보고서용 표현

```text
본 PoC에서는 Kagenti를 자율 제어 계층이 아니라 운영 보조 계층으로 적용한다.
Kagenti agent는 state-aggregator API를 read-only로 조회해 device, node, telemetry configured ratio, telemetry freshness ratio, DeviceStatus freshness ratio, service binding 상태를 한국어로 요약하고, 운영자가 우선 확인해야 할 대상을 제안한다.
이를 통해 현장 운영자는 전체 device를 개별 명령으로 확인하기 전에 dashboard와 agent 요약으로 문제 위치를 빠르게 좁힐 수 있다.
```

## 현재 범위에서 제외하는 것

다음은 현재 Kagenti PoC의 목표가 아니다.

- 완전 자동 복구
- agent가 직접 Kubernetes 리소스를 변경하는 구조
- agent가 actuator command를 직접 발행하는 구조
- workflow/offloading/placement 판단
- LLM 기반 전역 제어

위 항목은 현재 연구 방향의 구현 목표로 표현하지 않는다.
필요한 경우 별도 archive 또는 비교 검토 자료로만 다룬다.

## 관련 파일

```text
edge-orch/state-aggregator/app/models.py
edge-orch/state-aggregator/app/service.py
edge-orch/state-aggregator/app/main.py
edge-orch/state-aggregator/tests/test_api.py
```

## 테스트

state-aggregator 테스트는 다음 명령으로 실행한다.

```bash
cd /home/etri/jinuk/edge-orch/state-aggregator
PYTHONPATH=. .venv/bin/pytest -q tests
```
