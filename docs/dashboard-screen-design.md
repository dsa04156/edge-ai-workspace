# Dashboard Screen Design

## 목적

- 운영자가 디바이스, 노드, 서비스, telemetry freshness를 리소스 콘솔 흐름으로 읽게 한다.
- 현재 PoC 범위는 통합 운영 가시화와 read-only preview다.
- 화면은 실행 버튼 중심이 아니라 관측값, 판단 근거, dry-run 계획 중심으로 설계한다.

## 전체 프레임

- Resource rail: 검은 좌측 레일, Edge AI Resource Console identity, Overview, Assets, AI Pipeline.
- Command bar: cluster context, global search, 마지막 갱신 시각, refresh.
- Workspace: 현재 선택된 page만 표시하며 카드형 장식 대신 resource row와 flat panel로 구성한다.
- Inspector rail: State Explanation, read-only Qwen assistant.
- Dense scroll: 긴 목록, table, plan preview, inspector rail에만 허용.

## Overview

- Metric rows: node, device, telemetry, service resource, pod usage, binding.
- Current State Visualization: health ring, metric bars, status distribution, resource snapshot.
- Operations evidence: KPI catalog, node pressure, service profiles, latest sensor state.

## Assets

- Edge Nodes와 Devices를 같은 panel 안의 list-detail 구조로 표시한다.
- Service Topology는 Assets 안에 둔다. 목적은 서비스 실행이 아니라 디바이스-서비스 연결 구조 확인이다.

## AI Pipeline

- Summary strip으로 등록 디바이스, availability, telemetry freshness, validation 상태를 먼저 보여준다.
- Palette, graph canvas, inspector를 한 작업면으로 묶는다.
- Validation과 Execution Plan은 dry-run preview로만 표시한다.

## Deferred Resource Augmentation

- Resource Augmentation은 기능 재구상 전까지 dashboard navigation과 active page에서 제외한다.
- 기존 resource augmentation JS/CSS 자산은 재설계 참고용으로 보관할 수 있지만 운영 화면에서 로드하지 않는다.
- 다시 노출하려면 화면 정보 구조, 책임 범위, 검증 기준을 먼저 갱신한다.

## 표현 경계

- 유지: observed state, read-only explanation, dry-run, preview.
- 금지: dashboard apply/delete/restart, MQTT command publish, actuator command, runtime migration, autonomous orchestration completed.
- 자원증강은 재설계 전까지 현재 dashboard 운영 기능으로 표현하지 않는다.

## Responsive

- Desktop: dark left resource rail + compact command bar + main workspace + sticky inspector rail.
- Tablet: resource rail은 가로 tab으로 접고 inspector rail을 본문 아래로 내리며, graph는 세로 stack으로 전환한다.
- Mobile: resource rail은 가로 스크롤 tab으로 접히고, metric row와 panel header는 단일열로 전환한다.
