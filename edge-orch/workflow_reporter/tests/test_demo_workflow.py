from workflow_reporter.demo_workflow import run_vision_pipeline


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeReporter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def send_event(self, event) -> dict:
        payload = event.model_dump(mode="json")
        self.events.append(payload)
        return {"ok": True, "event_type": payload["event_type"]}


def test_run_vision_pipeline_emits_stage_events(monkeypatch):
    def fake_post(url, json, timeout):
        return DummyResponse(
            {
                "decision": {
                    "workflow_id": json["workflow_id"],
                    "stage_id": json["stage_id"],
                    "target_node": "etri-ser0001-CG0MSB",
                    "decision_reason": "selected server",
                    "action_type": "migrate",
                    "score_breakdown": {},
                }
            }
        )

    monkeypatch.setattr("workflow_reporter.demo_workflow.httpx.post", fake_post)
    reporter = FakeReporter()

    result = run_vision_pipeline(
        workflow_id="wf-vision-001",
        placement_engine_url="http://placement-engine.test",
        reporter=reporter,
        simulate_delay=False,
    )

    assert len(result.stages) == 5
    assert result.stages[2].stage_id == "inference"
    assert reporter.events[0]["event_type"] == "stage_start"
    assert reporter.events[-1]["event_type"] == "workflow_end"
    assert reporter.events[-1]["stage_id"] == "result_delivery"


def test_run_vision_pipeline_reports_migration_when_replanned(monkeypatch):
    def fake_post(url, json, timeout):
        target_node = "etri-dev0001-jetorn" if json["stage_id"] == "inference" else "etri-dev0002-raspi5"
        return DummyResponse(
            {
                "decision": {
                    "workflow_id": json["workflow_id"],
                    "stage_id": json["stage_id"],
                    "target_node": target_node,
                    "decision_reason": "selected target",
                    "action_type": "migrate",
                    "score_breakdown": {},
                }
            }
        )

    monkeypatch.setattr("workflow_reporter.demo_workflow.httpx.post", fake_post)
    reporter = FakeReporter()

    run_vision_pipeline(
        workflow_id="wf-vision-002",
        placement_engine_url="http://placement-engine.test",
        current_placement={"inference": "etri-dev0002-raspi5"},
        reporter=reporter,
        simulate_delay=False,
    )

    migration_events = [event for event in reporter.events if event["event_type"] == "migration_event"]
    assert len(migration_events) == 1
    assert migration_events[0]["stage_id"] == "inference"
    assert migration_events[0]["from_node"] == "etri-dev0002-raspi5"
    assert migration_events[0]["to_node"] == "etri-dev0001-jetorn"
