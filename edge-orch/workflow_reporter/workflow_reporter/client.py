from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from .models import WorkflowEvent


class WorkflowReporter:
    def __init__(
        self,
        aggregator_url: str | None = None,
        fallback_log_path: str | None = None,
        timeout_seconds: float = 3.0,
        retries: int = 2,
        retry_delay_seconds: float = 0.5,
    ) -> None:
        self.aggregator_url = aggregator_url or os.getenv(
            "STATE_AGGREGATOR_URL", "http://state-aggregator:8000/workflow-event"
        )
        self.fallback_log_path = Path(
            fallback_log_path
            or os.getenv("WORKFLOW_REPORTER_FALLBACK_LOG", "./workflow_reporter_fallback.jsonl")
        )
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.retry_delay_seconds = retry_delay_seconds

    def send_event(self, event: WorkflowEvent) -> dict:
        payload = event.model_dump(mode="json")
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            try:
                response = httpx.post(
                    self.aggregator_url,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_delay_seconds)

        self._append_fallback(payload, last_error)
        raise RuntimeError(f"Failed to send workflow event to {self.aggregator_url}") from last_error

    def _append_fallback(self, payload: dict, error: Exception | None) -> None:
        self.fallback_log_path.parent.mkdir(parents=True, exist_ok=True)
        fallback_record = {
            "payload": payload,
            "error": str(error) if error else "unknown",
        }
        with self.fallback_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(fallback_record, ensure_ascii=True))
            handle.write("\n")
