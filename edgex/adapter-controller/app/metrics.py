from __future__ import annotations

from collections import Counter
from typing import Any


def render_discovery_metrics(
    inventory: Any,
    registrations: list[Any],
) -> str:
    state_counts = Counter(item.state for item in inventory.candidates)
    stale = sum(item.presence == "stale" for item in inventory.candidates)
    plugin_errors = sum(len(node.scan_errors) for node in inventory.nodes)
    attempts = sum(item.attempt for item in registrations)
    failures = sum(
        item.attempt
        if item.status == "FAILED"
        else max(0, item.attempt - 1)
        for item in registrations
    )
    completed = [
        item
        for item in registrations
        if item.completed_at is not None
    ]
    durations = [
        max(0.0, (item.completed_at - item.started_at).total_seconds())
        for item in completed
    ]
    lines = [
        "# HELP discovery_candidates_total Current discovery candidates.",
        "# TYPE discovery_candidates_total gauge",
        f"discovery_candidates_total {len(inventory.candidates)}",
        "# HELP discovery_candidates_by_state Current candidates by state.",
        "# TYPE discovery_candidates_by_state gauge",
    ]
    for state, count in sorted(state_counts.items()):
        lines.append(
            f'discovery_candidates_by_state{{state="{state}"}} {count}'
        )
    lines.extend(
        [
            "# HELP registration_attempts_total Persisted registration attempts.",
            "# TYPE registration_attempts_total counter",
            f"registration_attempts_total {attempts}",
            "# HELP registration_failures_total Persisted failed registrations.",
            "# TYPE registration_failures_total counter",
            f"registration_failures_total {failures}",
            "# HELP registration_duration_seconds Registration duration summary.",
            "# TYPE registration_duration_seconds summary",
            f"registration_duration_seconds_count {len(durations)}",
            f"registration_duration_seconds_sum {sum(durations):.6f}",
            "# HELP discovery_plugin_errors_total Current node discovery errors.",
            "# TYPE discovery_plugin_errors_total gauge",
            f"discovery_plugin_errors_total {plugin_errors}",
            "# HELP stale_candidates_total Current stale candidates.",
            "# TYPE stale_candidates_total gauge",
            f"stale_candidates_total {stale}",
            "",
        ]
    )
    return "\n".join(lines)
