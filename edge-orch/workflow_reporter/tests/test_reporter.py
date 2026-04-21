from pathlib import Path

from workflow_reporter.client import WorkflowReporter
from workflow_reporter.helpers import report_migration, report_stage_end, report_stage_start


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_stage_helpers_send_expected_events(monkeypatch):
    sent_payloads = []

    def fake_post(url, json, timeout):
        sent_payloads.append({"url": url, "json": json, "timeout": timeout})
        return DummyResponse({"ok": True, "event_type": json["event_type"]})

    monkeypatch.setattr("workflow_reporter.client.httpx.post", fake_post)
    reporter = WorkflowReporter(aggregator_url="http://aggregator.test/workflow-event")

    report_stage_start("wf-1", "inference", "stage-a", "decode", "node-a", reporter=reporter)
    report_migration(
        "wf-1",
        "inference",
        "stage-a",
        "decode",
        "node-a",
        "node-b",
        transfer_time_ms=123,
        reporter=reporter,
    )
    report_stage_end(
        "wf-1",
        "inference",
        "stage-a",
        "decode",
        "node-b",
        exec_time_ms=456,
        reporter=reporter,
    )

    assert [item["json"]["event_type"] for item in sent_payloads] == [
        "stage_start",
        "migration_event",
        "stage_end",
    ]
    assert sent_payloads[1]["json"]["to_node"] == "node-b"


def test_reporter_falls_back_to_jsonl(monkeypatch, tmp_path: Path):
    def fake_post(url, json, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr("workflow_reporter.client.httpx.post", fake_post)
    fallback_path = tmp_path / "fallback.jsonl"
    reporter = WorkflowReporter(
        aggregator_url="http://aggregator.test/workflow-event",
        fallback_log_path=str(fallback_path),
        retries=0,
    )

    try:
        report_stage_start("wf-2", "inference", "stage-b", "preprocess", "node-c", reporter=reporter)
    except RuntimeError:
        pass

    lines = fallback_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "stage_start" in lines[0]
