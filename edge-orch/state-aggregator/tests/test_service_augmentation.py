from datetime import datetime, timedelta, timezone

from app.service_augmentation import (
    ServiceAugmentationEvaluator,
    ServiceAugmentationSignals,
)


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def _signals(**updates) -> ServiceAugmentationSignals:
    values = {
        "input_valid": True,
        "input_reason": "input_ready",
        "model_ready": True,
        "metrics_valid": True,
        "metrics_reason": "metrics_fresh",
        "resource_metric_source": "prometheus-node",
        "service_metric_source": "service-api",
        "cpu_ratio": 0.91,
        "memory_ratio": 0.4,
        "gpu_pressure": False,
        "gpu_percent": 20.0,
        "processing_latency_p95_ms": 700.0,
        "backlog": 4,
        "throughput_per_second": 1.5,
        "server1_pod_ready": True,
        "server1_endpoint_ready": True,
        "server1_model_ready": True,
        "server1_resource_available": True,
    }
    values.update(updates)
    return ServiceAugmentationSignals(**values)


def test_evaluator_requires_five_minutes_resource_and_three_minutes_service_pressure() -> None:
    evaluator = ServiceAugmentationEvaluator()

    first = evaluator.evaluate(_signals(), now=NOW)
    almost = evaluator.evaluate(_signals(), now=NOW + timedelta(minutes=4, seconds=59))
    ready = evaluator.evaluate(_signals(), now=NOW + timedelta(minutes=5))

    assert first.state == "OBSERVING"
    assert almost.state == "OBSERVING"
    assert ready.state == "RECOMMENDED"
    assert ready.recommendation == "scale-up"
    assert ready.dwell.resource_pressure_seconds == 300
    assert ready.dwell.service_pressure_seconds == 300
    assert ready.apply_state == "observed-only"


def test_evaluator_does_not_use_equipment_anomaly_score() -> None:
    evaluator_a = ServiceAugmentationEvaluator()
    evaluator_b = ServiceAugmentationEvaluator()

    # The signal contract intentionally has no anomaly or anomaly_score field.
    normal_equipment = evaluator_a.evaluate(_signals(), now=NOW)
    anomalous_equipment = evaluator_b.evaluate(_signals(), now=NOW)

    assert normal_equipment == anomalous_equipment
    assert normal_equipment.anomaly_signal_used is False
    assert "anomaly_score" not in ServiceAugmentationSignals.__dataclass_fields__


def test_evaluator_blocks_invalid_input_metrics_model_and_server1() -> None:
    evaluator = ServiceAugmentationEvaluator()
    state = evaluator.evaluate(
        _signals(
            input_valid=False,
            input_reason="sensor_stale",
            model_ready=False,
            metrics_valid=False,
            metrics_reason="metrics_invalid_or_stale",
            server1_pod_ready=False,
            server1_endpoint_ready=False,
            server1_model_ready=False,
            server1_resource_available=False,
        ),
        now=NOW,
    )

    assert state.state == "BLOCKED"
    assert state.apply_state == "blocked"
    assert state.reason_codes == [
        "sensor_stale",
        "model_not_ready",
        "metrics_invalid_or_stale",
        "server1_pod_not_ready",
        "server1_endpoint_not_ready",
        "server1_model_not_ready",
        "server1_resource_insufficient",
    ]


def test_evaluator_resets_pressure_dwell_when_pressure_clears() -> None:
    evaluator = ServiceAugmentationEvaluator()
    evaluator.evaluate(_signals(), now=NOW)
    cleared = evaluator.evaluate(
        _signals(
            cpu_ratio=0.4,
            memory_ratio=0.4,
            processing_latency_p95_ms=100,
            backlog=0,
            throughput_per_second=2.0,
        ),
        now=NOW + timedelta(minutes=4),
    )
    restarted = evaluator.evaluate(_signals(), now=NOW + timedelta(minutes=5))

    assert cleared.state == "NORMAL"
    assert restarted.state == "OBSERVING"
    assert restarted.dwell.resource_pressure_seconds == 0


def test_augmented_state_enters_cooldown_only_after_scale_down_dwell_and_cooldown() -> None:
    evaluator = ServiceAugmentationEvaluator()
    evaluator.evaluate(_signals(), now=NOW)
    evaluator.evaluate(_signals(), now=NOW + timedelta(minutes=5))
    evaluator.mark_augmented(now=NOW + timedelta(minutes=5))

    low = _signals(
        cpu_ratio=0.5,
        memory_ratio=0.5,
        processing_latency_p95_ms=300,
        backlog=0,
        throughput_per_second=2.0,
    )
    augmented = evaluator.evaluate(low, now=NOW + timedelta(minutes=5))
    almost = evaluator.evaluate(low, now=NOW + timedelta(minutes=19, seconds=59))
    cooldown = evaluator.evaluate(low, now=NOW + timedelta(minutes=20))
    normal = evaluator.evaluate(low, now=NOW + timedelta(minutes=35))

    assert augmented.state == "AUGMENTED"
    assert almost.state == "AUGMENTED"
    assert cooldown.state == "COOLDOWN"
    assert cooldown.recommendation == "scale-down"
    assert normal.state == "NORMAL"


def test_evaluator_records_observed_before_and_after_performance_snapshots() -> None:
    evaluator = ServiceAugmentationEvaluator()
    evaluator.evaluate(_signals(), now=NOW)
    recommended = evaluator.evaluate(_signals(), now=NOW + timedelta(minutes=5))
    evaluator.mark_augmented(now=NOW + timedelta(minutes=5))
    augmented = evaluator.evaluate(
        _signals(
            cpu_ratio=0.55,
            processing_latency_p95_ms=320,
            backlog=0,
            throughput_per_second=2.4,
        ),
        now=NOW + timedelta(minutes=5, seconds=5),
    )

    assert recommended.performance_comparison.before.processing_latency_p95_ms == 700
    assert recommended.performance_comparison.after is None
    assert augmented.performance_comparison.before.processing_latency_p95_ms == 700
    assert augmented.performance_comparison.after.processing_latency_p95_ms == 320
    assert augmented.performance_comparison.after.throughput_per_second == 2.4
