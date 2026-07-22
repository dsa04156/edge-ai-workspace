from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import (
    AxisValues,
    LatestObservation,
    ModelObservation,
    RuntimeCounters,
    ServiceStatus,
    SourceIdentity,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.worker_started = False
        self.stopped = False
        self.latest = LatestObservation(
            origin=1_000_000_000,
            observed_at=datetime.now(timezone.utc),
            values=AxisValues(x=3, y=4, z=0),
            magnitude=5.0,
            score=0.25,
            anomaly=False,
        )

    async def start(self) -> None:
        self.worker_started = True

    async def stop(self) -> None:
        self.worker_started = False
        self.stopped = True

    def status(self) -> ServiceStatus:
        return ServiceStatus(
            status="normal",
            input_state="fresh",
            model_state="ready",
            source=SourceIdentity(
                devices=[
                    "virtual-acceleration-x-001",
                    "virtual-acceleration-y-001",
                    "virtual-acceleration-z-001",
                ]
            ),
            latest=self.latest,
            model=ModelObservation(
                algorithm="online-gaussian-baseline-v1",
                sample_count=30,
                warmup_samples=30,
                threshold=4.0,
                baseline_mean=5.0,
                baseline_stddev=1.0,
                stddev_floor=1.0,
            ),
            counters=RuntimeCounters(frames_processed=30),
        )

    def results(self, limit: int) -> list[LatestObservation]:
        return [self.latest][-limit:]


def test_status_results_and_probes_are_read_only_and_use_v1_schema() -> None:
    runtime = FakeRuntime()

    with TestClient(create_app(runtime=runtime)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ready"}
        status = client.get("/api/v1/status")
        results = client.get("/api/v1/results?limit=1")
        assert client.get("/api/v1/results?limit=0").status_code == 422
        assert client.post("/api/v1/status").status_code == 405

    assert runtime.stopped is True
    assert status.status_code == 200
    assert status.json()["apiVersion"] == "v1"
    assert status.json()["mode"] == "live"
    assert status.json()["inputState"] == "fresh"
    assert status.json()["modelState"] == "ready"
    assert results.status_code == 200
    assert results.json()["count"] == 1
    assert results.json()["results"][0]["origin"] == 1_000_000_000
