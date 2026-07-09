# Edge AI Operations Dashboard Design System

## 1. Atmosphere & Identity

A Headlamp-inspired Kubernetes operations console for mixed-device edge AI. It should feel like a cluster resource browser first: a dark persistent resource rail, compact top search/context bar, yellow active navigation marker, dense dark work surfaces, and table/list-detail inspection. The interface is not a marketing dashboard; it is an operator tool for finding cluster, device, telemetry, service binding, and resource augmentation evidence quickly.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|------|-------|-------|------|-------|
| Surface/base | --console-bg | #1f2428 | #1f2428 | Page background |
| Surface/nav | --console-nav | #07090b | #07090b | Left navigation rail |
| Surface/grid | --console-grid | rgba(255, 255, 255, 0.035) | rgba(255, 255, 255, 0.035) | Subtle resource grid |
| Surface/panel | --console-panel | #24292e | #24292e | Cards and panels |
| Surface/soft | --console-soft | #2b3137 | #2b3137 | Nested blocks |
| Surface/header | --console-header | #262b30 | #262b30 | Top app/search bar |
| Text/primary | --console-text | #f4f5f6 | #f4f5f6 | Main text |
| Text/secondary | --console-muted | #a8b0b8 | #a8b0b8 | Metadata |
| Border/default | --console-border | #3a4148 | #3a4148 | Panel borders |
| Border/strong | --console-border-strong | #555f68 | #555f68 | Selected outlines |
| Accent/primary | --console-accent | #f4ea2a | #f4ea2a | Active navigation and primary selection |
| Accent/deep | --console-accent-deep | #c9bd12 | #c9bd12 | Pressed yellow state |
| Status/success | --console-success | #3dd56d | #3dd56d | Healthy/running |
| Status/warning | --console-warning | #f5bd4f | #f5bd4f | Warning |
| Status/error | --console-error | #ff6b6b | #ff6b6b | Critical/offline |
| Status/info | --console-info | #5fb5ff | #5fb5ff | Informational |

### Rules

- Use the black left navigation rail and yellow selected resource state as the dashboard signature.
- Use dark panels on a charcoal app background; avoid bright white cards in the content area.
- Keep color quiet. Yellow is for selection/action, status colors are for state only.
- Status colors are reserved for state, not decoration.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Tracking | Usage |
|-------|------|--------|-------------|----------|-------|
| Display | 34px | 800 | 1.1 | 0 | Dashboard title |
| H1 | 28px | 800 | 1.15 | 0 | Page title |
| H2 | 20px | 750 | 1.25 | 0 | Panel title |
| H3 | 15px | 750 | 1.35 | 0 | Card title |
| Body | 14px | 500 | 1.55 | 0 | Default text |
| Body/sm | 13px | 500 | 1.45 | 0 | Secondary text |
| Caption | 12px | 650 | 1.35 | 0 | Labels and metadata |

### Font Stack

- Primary: "Aptos", "Pretendard", "Noto Sans KR", "IBM Plex Sans KR", system-ui, sans-serif
- Mono: "JetBrains Mono", "SFMono-Regular", Consolas, monospace

### Rules

- Use tabular numbers for metrics and resource values.
- Do not use negative letter spacing in compact cards.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a base of 4px.

| Token | Value | Usage |
|-------|-------|-------|
| --space-1 | 4px | Tight icon/label gap |
| --space-2 | 8px | Compact controls |
| --space-3 | 12px | Small card gap |
| --space-4 | 16px | Panel padding |
| --space-5 | 20px | Section gap |
| --space-6 | 24px | Page rhythm |
| --space-8 | 32px | Major groups |

### Grid

- Max content width: 1600px
- Page shell: full-width operational canvas with 16px edge margin
- Main layout: full-height dark left navigation rail, compact top search/context bar, primary content column, sticky right operator rail
- Breakpoints: mobile 720px, tablet 1040px, desktop 1280px

### Rules

- Prefer list-detail panels for devices, services, events, and resource choices.
- Avoid nested scroll inside explanation panels; the right rail owns scrolling.

## 5. Components

### Command Header

- Structure: product identity, cluster context, global search affordance, update timestamp, refresh button.
- States: refresh button has hover, active, and focus states.
- Motion: hover uses transform only.

### Resource Navigation Rail

- Structure: persistent left rail with page/resource buttons.
- Variants: desktop vertical rail, mobile horizontal scroll.
- Accessibility: active tab uses `aria-pressed=true`.
- States: selected item uses yellow background, black text, and a left marker.

### Metric Card

- Structure: label, large value, caption.
- Variants: default, success, warning, danger.
- Spacing: `--space-4` padding, `--space-3` inner gap.

### List Detail Workspace

- Structure: left scrollable list, right detail cards.
- States: selected row uses cyan border and soft cyan background.

## 6. Motion & Interaction

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 140ms | ease-out | Button active |
| Standard | 220ms | ease-in-out | Card hover and tab switch |
| Emphasis | 420ms | cubic-bezier(0.16, 1, 0.3, 1) | Workflow packet animation |

### Rules

- Animate only `transform`, `opacity`, and background/border color.
- Respect `prefers-reduced-motion`.

## 7. Depth & Surface

### Strategy

Restrained Headlamp-like elevation: panels rely on borders and tonal contrast first; shadows are shallow and only separate the app bar, sticky rail, and selected work surfaces.

| Level | Value | Usage |
|-------|-------|-------|
| Panel | 0 1px 2px rgba(15, 23, 42, 0.05) | Main panels |
| Raised | 0 12px 28px rgba(15, 23, 42, 0.10) | App bar, sticky rails, selected states |
| Border | 1px solid var(--console-border) | Cards, dividers |

## 8. Screen Architecture

### Dashboard Frame

The dashboard is a single operational console, not a landing page. The frame is fixed around five regions:

1. Resource navigation rail: Edge AI identity, Overview, Assets, AI Pipeline, Resource Augmentation.
2. App bar: cluster context, global search affordance, current observation time, refresh action.
3. Main workspace: active page content only.
4. Operator rail: explanation panel and read-only assistant.
5. Scroll containers: only dense lists, tables, code previews, and the right rail own scrolling.

### Page Blueprints

Overview:

- First row: KPI cards for nodes, devices, telemetry, service resources, pod usage, and service binding.
- Second row: current state visualization with health ring, metric bars, status distribution, and resource snapshot.
- Third row: collected operational evidence, split into KPI catalog, node pressure, service profiles, and latest sensor state.

Assets:

- Primary panel: edge nodes and devices as a list-detail inventory.
- Secondary panel: service topology under Assets, because it explains device-service binding rather than runtime execution.

AI Pipeline:

- Summary strip first.
- Builder controls second.
- Workspace split into node palette, graph canvas, and inspector.
- Validation and execution plan stay below the canvas as dry-run evidence.

Resource Augmentation:

- Summary cards first.
- At-a-glance decision strip second.
- Runtime flow graph and playback evidence third.
- Candidate resources and read-only plan next.
- Resource pool and resource twin inspector last.

### Final CSS Layer

`dashboard-screen.css` is the final Headlamp-style visual contract. Earlier CSS files may keep legacy component rules, but this layer owns:

- dark Headlamp-like Kubernetes console color scheme and aliases for legacy `--line`, `--text`, `--muted`, status, and shadow tokens
- app bar, left resource navigation rail, main workspace, and operator rail geometry
- panel, KPI, list row, chip, table, graph, and workflow surface treatment
- responsive behavior at 1180px, 900px, 760px, and 520px
- CJK-safe headings and wrap-safe technical values

No screen may introduce a new visible component pattern unless it is added here first.

### Scope Guardrails

- The dashboard may preview runtime decisions and dry-run plans.
- The dashboard must not imply Kubernetes apply/delete/restart, Device CR mutation, MQTT command publishing, actuator control, runtime migration, or fully autonomous orchestration.
- Resource augmentation is shown as observed runtime state or an explicit demo scenario, not as a scheduler execution surface.
