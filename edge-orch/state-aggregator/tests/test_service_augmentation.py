from datetime import datetime, timedelta, timezone

from app.service_augmentation import (
    ServiceAugmentationEvaluator,
    ServiceAugmentationSignals,
    build_service_augmentation_signals,
)
from app.service_demo_models import (
    ServiceDemoBinding,
    ServiceDemoPerformance,
    ServiceDemoProcessResources,
    ServiceDemoState,
)


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _signals(**updates) -> ServiceAugmentationSignals:
    values = {
        "input_valid": True,
        "model_ready": True,
        "performance_valid": True,
        "resource_valid": True,
        "cpu_ratio": 0.9,
        "memory_ratio": 0.4,
        "processing_latency_p95_ms": 5000.0,
        "backlog": 2,
        "throughput_per_second": 0.6,
        "candidate_ready": True,
        "observation_source": "process-self",
        "observation_scope": "main-process",
    }
    values.update(updates)
    return ServiceAugmentationSignals(**values)


def test_evaluator_recommends_only_after_resource_and_service_pressure_dwell() -> None:
    evaluator = ServiceAugmentationEvaluator()

    first = evaluator.evaluate(_signals(), now=NOW)
    almost = evaluator.evaluate(_signals(), now=NOW + timedelta(minutes=4, seconds=59))
    ready = evaluator.evaluate(_signals(), now=NOW + timedelta(minutes=5))

    assert first.state == "OBSERVING"
    assert almost.state == "OBSERVING"
    assert ready.state == "RECOMMENDED"
    assert ready.recommendation == "scale-up"
    assert ready.apply_state == "observed-only"
    assert ready.anomaly_signal_used is False


def test_evaluator_blocks_missing_observation_and_unready_candidate_fail_closed() -> None:
    evaluator = ServiceAugmentationEvaluator()
    unavailable = evaluator.evaluate(_signals(resource_valid=False), now=NOW)

    assert unavailable.state == "BLOCKED"
    assert "resource_observation_unavailable" in unavailable.reason_codes

    evaluator = ServiceAugmentationEvaluator()
    evaluator.evaluate(_signals(candidate_ready=False), now=NOW)
    blocked = evaluator.evaluate(
        _signals(candidate_ready=False), now=NOW + timedelta(minutes=5)
    )

    assert blocked.state == "BLOCKED"
    assert blocked.recommendation == "none"
    assert "augmentation_candidate_not_ready" in blocked.reason_codes


def test_signal_builder_uses_process_fallback_when_cadvisor_has_no_sample() -> None:
    demo = ServiceDemoState(
        generated_at=NOW,
        mode="live",
        status="normal",
        input_state="fresh",
        model_state="ready",
        binding=ServiceDemoBinding(),
        performance=ServiceDemoPerformance(
            observed_at=NOW,
            window_seconds=300,
            processing_latency_p95_ms=1200,
            backlog=0,
            throughput_per_second=1.2,
            sample_count=30,
            metrics_valid=True,
        ),
        process_resources=ServiceDemoProcessResources(
            observed_at=NOW,
            source="process-self",
            scope="main-process",
            cpu_cores=0.1,
            memory_rss_mib=64,
            sample_interval_seconds=5,
            metrics_valid=True,
        ),
    )
    profile = {
        "generated_at": NOW.isoformat(),
        "current_usage": {
            "cpu_cores": None,
            "memory_working_set_mib": None,
            "usage_coverage_ratio": 0,
        },
        "resource_requirements": {
            "limits": {"cpu_cores": 0.25, "memory_mib": 128},
        },
    }

    signals = build_service_augmentation_signals(
        demo,
        profile,
        candidate_ready=False,
        now=NOW,
    )

    assert signals.resource_valid is True
    assert signals.cpu_ratio == 0.4
    assert signals.memory_ratio == 0.5
    assert signals.observation_source == "process-self"
    assert signals.observation_scope == "main-process"
