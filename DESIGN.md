# Edge AI Resource Console Design System

## 1. Atmosphere & Identity

The dashboard is a dense Kubernetes-style resource console for a mixed-device edge AI PoC. It should read as an operator workspace: persistent resource navigation, command search, resource rows, flat bordered panels, and a right-side inspector. It is not a card-heavy BI dashboard and not a marketing surface.

## 2. Color

| Role | Token | Value | Usage |
|------|-------|-------|-------|
| App background | --console-bg | #15191d | Page canvas |
| Resource rail | --console-rail | #07090b | Persistent navigation |
| Command bar | --console-command | #1b2025 | Top search/context bar |
| Panel | --console-panel | #20262b | Primary sections |
| Row | --console-row | #1a1f24 | Tables, metrics, list rows |
| Border | --console-border | #343c44 | Section separation |
| Text | --console-text | #eef2f5 | Main content |
| Muted | --console-muted | #9aa4ad | Metadata |
| Selection | --console-yellow | #f4ea2a | Active nav and primary action |
| Info | --console-blue | #49a6ff | Links and selected evidence |
| Healthy | --console-green | #3dd56d | Available state |
| Warning | --console-orange | #f5bd4f | Degraded/risk state |
| Error | --console-red | #ff6b6b | Unavailable state |

Rules:

- Yellow is only for selection and explicit primary action.
- Status colors are only for state.
- Panels use borders and tonal separation, not decorative shadows.

## 3. Typography

- Primary: "Aptos", "Pretendard", "Noto Sans KR", "IBM Plex Sans KR", system-ui, sans-serif
- Mono: "JetBrains Mono", "SFMono-Regular", Consolas, monospace
- Metrics and resource values use tabular numbers.
- Letter spacing stays at `0`.
- CJK labels use `word-break: keep-all`; technical values may wrap anywhere.

## 4. Layout

The screen has four fixed regions:

1. Resource rail: persistent left rail on desktop; horizontal resource tabs below 1180px.
2. Command bar: cluster context, global search, update time, refresh action.
3. Workspace: active page content only, built from resource rows and flat panels.
4. Inspector rail: state explanation and read-only assistant; sticky on desktop, stacked below content on tablet/mobile.

Breakpoints:

- Desktop: `rail command` / `rail workspace`, workspace split into content plus 376px inspector.
- Tablet: resource rail becomes horizontal, inspector stacks under workspace.
- Mobile: one-column workspace, metric rows become vertical.

## 5. Components

### Resource Rail

- Black rail, compact labels, yellow selected state.
- Active tab uses `aria-pressed=true`.
- Desktop buttons are row-like; tablet/mobile buttons are horizontally scrollable.

### Command Bar

- No hero treatment.
- Search is a command input, not a large page banner.
- Refresh is the only yellow action in the bar.

### Metric Row

- Metrics are rows, not cards.
- Structure: uppercase label, numeric value, caption.
- Desktop layout places value on the right; mobile stacks value under label.

### Panel

- Flat bordered surface, 4px radius.
- Header uses kicker, title, and metadata chips.
- No nested cards inside panel sections unless the content is a repeated item.

### Resource Lists and Tables

- Devices, nodes, services, resource candidates, and runtime evidence share the same row grammar.
- Long IDs and telemetry values wrap without overlapping.

### Inspector Rail

- Contains State Explanation and read-only assistant.
- It explains observed evidence and dry-run previews; it does not expose execution controls.

## 6. Motion & Interaction

- Motion is limited to real controls: hover, active, focus.
- Animate only `transform`, `background`, `border-color`, and `color`.
- Respect `prefers-reduced-motion`.

## 7. Final CSS Layer

`dashboard-screen.css` is the final Resource Console visual contract. It intentionally replaces the previous card-dashboard layer and owns:

- root console tokens and aliases for legacy dashboard variables
- app frame geometry: rail, command bar, workspace, inspector
- metric rows, panels, resource rows, tables, graph surfaces, and augmentation previews
- responsive behavior at 1180px, 900px, 760px, and 520px
- CJK-safe headings and wrap-safe technical values

## 8. Scope Guardrails

- The dashboard may show observed runtime state, resource candidates, read-only decisions, and dry-run plans.
- It must not imply Kubernetes apply/delete/restart, Device CR mutation, MQTT command publishing, actuator control, runtime migration, or completed autonomous orchestration.
- Resource augmentation is visualized as observed state or explicit demo scenario evidence, not as a scheduler execution surface.
