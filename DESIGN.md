# Edge AI Operations Dashboard Design System

## 1. Atmosphere & Identity

A Kubernetes-style operations console for mixed-device edge AI. It should feel clear, inspectable, and controlled: a bright working surface with a deep navy command header, cyan active states, compact status cards, and list-detail layouts that make runtime state easy to scan.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|------|-------|-------|------|-------|
| Surface/base | --console-bg | #eef4f7 | #0b1117 | Page background |
| Surface/grid | --console-grid | rgba(34, 66, 80, 0.08) | rgba(120, 190, 210, 0.08) | Background grid |
| Surface/panel | --console-panel | #ffffff | #111a22 | Cards and panels |
| Surface/soft | --console-soft | #f7fbfd | #17232d | Nested blocks |
| Surface/header | --console-header | #102b3a | #07131c | Top command header |
| Text/primary | --console-text | #102235 | #f4f8fb | Main text |
| Text/secondary | --console-muted | #5b7181 | #9fb1bd | Metadata |
| Border/default | --console-border | #d7e3ea | #243645 | Panel borders |
| Border/strong | --console-border-strong | #b9ccd8 | #365064 | Selected outlines |
| Accent/primary | --console-accent | #008a9a | #21c4d5 | Active tabs and focus |
| Accent/deep | --console-accent-deep | #004c5c | #063a48 | Primary buttons |
| Status/success | --console-success | #0a8f5a | #32d583 | Healthy/running |
| Status/warning | --console-warning | #d97706 | #f5bd4f | Warning |
| Status/error | --console-error | #dc2626 | #ff6f61 | Critical/offline |
| Status/info | --console-info | #1d6fd6 | #63a7ff | Informational |

### Rules

- Use the navy header and cyan active underline as the dashboard signature.
- Use white panels on the grid background; avoid dark cards in the content area.
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
- Main layout: one primary content column plus a sticky right operator rail
- Breakpoints: mobile 720px, tablet 1040px, desktop 1280px

### Rules

- Prefer list-detail panels for devices, services, events, and resource choices.
- Avoid nested scroll inside explanation panels; the right rail owns scrolling.

## 5. Components

### Command Header

- Structure: product eyebrow, dashboard title, update timestamp, refresh button.
- States: refresh button has hover, active, and focus states.
- Motion: hover uses transform only.

### Segmented Navigation

- Structure: horizontal tab bar with one active segment.
- Variants: desktop equal columns, mobile horizontal scroll.
- Accessibility: active tab uses `aria-pressed=true`.

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

Mixed, but restrained: white panels use a subtle border plus a soft tinted shadow; inner blocks use tonal shifts.

| Level | Value | Usage |
|-------|-------|-------|
| Panel | 0 8px 22px rgba(24, 57, 74, 0.08) | Main panels |
| Raised | 0 14px 34px rgba(24, 57, 74, 0.12) | Selected and hover states |
| Border | 1px solid var(--console-border) | Cards, dividers |

## 8. Screen Architecture

### Dashboard Frame

The dashboard is a single operational console, not a landing page. The frame is fixed around five regions:

1. Command header: product identity, current observation time, refresh action.
2. Page switcher: Overview, Assets, AI Pipeline, Resource Augmentation.
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

`dashboard-screen.css` is the final visual contract. Earlier CSS files may keep legacy component rules, but this layer owns:

- light console color scheme and aliases for legacy `--line`, `--text`, `--muted`, status, and shadow tokens
- header, page switcher, main workspace, and operator rail geometry
- panel, KPI, list row, chip, table, graph, and workflow surface treatment
- responsive behavior at 1180px, 900px, 760px, and 520px
- CJK-safe headings and wrap-safe technical values

No screen may introduce a new visible component pattern unless it is added here first.

### Scope Guardrails

- The dashboard may preview runtime decisions and dry-run plans.
- The dashboard must not imply Kubernetes apply/delete/restart, Device CR mutation, MQTT command publishing, actuator control, runtime migration, or fully autonomous orchestration.
- Resource augmentation is shown as observed runtime state or an explicit demo scenario, not as a scheduler execution surface.
