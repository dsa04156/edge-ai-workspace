# Dashboard Screen Design

## 목적

- 운영자가 디바이스, 노드, 서비스, telemetry freshness, 자원증강 후보를 한 화면 흐름으로 읽게 한다.
- 현재 PoC 범위는 통합 운영 가시화와 read-only preview다.
- 화면은 실행 버튼 중심이 아니라 관측값, 판단 근거, dry-run 계획 중심으로 설계한다.

## 전체 프레임

- Resource navigation rail: 검은 좌측 레일, Edge AI identity, Overview, Assets, AI Pipeline, Resource Augmentation.
- App bar: cluster context, global search, 마지막 갱신 시각, refresh.
- Main workspace: 현재 선택된 page만 표시.
- Operator rail: State Explanation, read-only Qwen assistant.
- Dense scroll: 긴 목록, table, plan preview, operator rail에만 허용.

## Overview

- KPI cards: node, device, telemetry, service resource, pod usage, binding.
- Current State Visualization: health ring, metric bars, status distribution, resource snapshot.
- Operations evidence: KPI catalog, node pressure, service profiles, latest sensor state.

## Assets

- Edge Nodes와 Devices를 같은 panel 안의 list-detail 구조로 표시.
- Service Topology는 Assets 안에 둔다. 목적은 서비스 실행이 아니라 디바이스-서비스 연결 구조 확인이다.

## AI Pipeline

- Summary strip으로 등록 디바이스, availability, telemetry freshness, validation 상태를 먼저 보여준다.
- Palette, graph canvas, inspector를 한 작업면으로 묶는다.
- Validation과 Execution Plan은 dry-run preview로만 표시한다.

## Resource Augmentation

- Summary cards: profile, observed runtime, available, allocated, risk, candidate, selected, decision.
- At-a-glance: current phase, AI workload, target device, selected resources, augmented device plan.
- Runtime flow: graph, playback, decision path, evidence timeline.
- Candidate resources: read-only decision detail과 함께 표시.
- Resource pool: registry/runtime instance table과 selected resource inspector.

## 표현 경계

- 유지: observed runtime, read-only decision, dry-run, preview, resource candidate, augmented device plan.
- 금지: dashboard apply/delete/restart, MQTT command publish, actuator command, runtime migration, autonomous orchestration completed.
- 자원증강은 기본 observed 상태와 명시적 demo 상태를 분리한다.

## Responsive

- Desktop: Headlamp형 dark left resource rail + compact search app bar + main workspace + sticky operator rail.
- Tablet: resource rail은 가로 tab으로 접고 operator rail을 본문 아래로 내리며, graph는 세로 stack으로 전환.
- Mobile: resource rail은 가로 스크롤 tab으로 접히고, KPI는 1~2열, panel header는 단일열.
