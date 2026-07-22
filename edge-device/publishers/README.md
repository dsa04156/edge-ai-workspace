# Sense HAT publisher 검증 fixture

이 디렉터리의 Sense HAT publisher와 systemd unit은 교체 예정인 장비별 검증 fixture다. 현재 EdgeX 운영 배포의 고정 입력 계약이나 완료 기준으로 사용하지 않는다.

현재 root `edgex/k8s/kustomization.yaml`은 MQTT-mode agent, `device-mqtt`, edge-local broker를 배포하지 않는다. 따라서 이 디렉터리에 남은 MQTT 송신 방식과 과거 topic은 current telemetry plane이나 fallback이 아니다.

새 publisher 또는 Protocol Adapter를 연결할 때는 다음 계약만 지킨다.

```text
센서 / PLC / 장비
  -> Protocol Adapter
  -> http://127.0.0.1:18080/v1/events
  -> edge-telemetry-agent -> SQLite outbox
  -> HTTPS/mTLS ingest gateway
  -> EdgeX Core Data / PostgreSQL
```

- canonical EdgeX v3 Event를 만든다.
- agent의 `202 queued`와 동일 Event ID를 확인한다.
- 중앙 장애 중에는 SQLite outbox에 보존하고 persisted ACK 뒤에만 삭제한다.
- MQTT-only 장비는 실제 필요성을 확인한 뒤 별도 adapter와 broker를 독립 검증한다.

Sense HAT publisher 교체 작업은 telemetry plane과 별도 변경으로 진행한다.
