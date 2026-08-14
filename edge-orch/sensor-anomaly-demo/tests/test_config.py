import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_load_documented_defaults(monkeypatch) -> None:
    for name in (
        "LOCAL_DATA_BASE_URL",
        "POLL_INTERVAL_SECONDS",
        "INPUT_STALE_SECONDS",
        "HTTP_TIMEOUT_SECONDS",
        "WARMUP_SAMPLES",
        "ANOMALY_THRESHOLD",
        "STDDEV_FLOOR",
        "EWMA_ALPHA",
        "CONTEXT_MAX_SKEW_SECONDS",
        "VIBRATION_WINDOW_SAMPLES",
        "TEMPERATURE_WINDOW_SAMPLES",
        "VIBRATION_WEIGHT",
        "TEMPERATURE_WEIGHT",
        "MODEL_BACKEND",
        "MODEL_VERSION",
        "SERVICE_DEVICE_ID",
        "SERVICE_ASSET_ID",
        "SERVICE_NODE_ID",
        "RESULT_DB_PATH",
        "RESULT_RETENTION_ROWS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.local_data_base_url == (
        "http://device-serial-jetson.edgex-edge.svc.cluster.local:59910"
    )
    assert settings.poll_interval_seconds == 0.5
    assert settings.input_stale_seconds == 10.0
    assert settings.http_timeout_seconds == 2.0
    assert settings.warmup_samples == 30
    assert settings.anomaly_threshold == 4.0
    assert settings.stddev_floor == 1.0
    assert settings.ewma_alpha == 0.05
    assert settings.context_max_skew_seconds == 2.0
    assert settings.vibration_window_samples == 20
    assert settings.temperature_window_samples == 10
    assert settings.vibration_weight == 0.7
    assert settings.temperature_weight == 0.3
    assert settings.model_backend == "online-baseline"
    assert settings.model_version == "baseline-1.0.0"
    assert settings.service_device_id == "arduino-001"
    assert settings.service_asset_id == "arduino-001"
    assert settings.service_node_id == "etri-dev0001-jetorn"
    assert settings.result_db_path == "/tmp/sensor-anomaly-demo/results.db"
    assert settings.result_retention_rows == 100_000


def test_settings_reject_zero_total_weight_and_impossible_alignment_ttl() -> None:
    with pytest.raises(ValidationError, match="score weight"):
        Settings(vibration_weight=0, temperature_weight=0)
    with pytest.raises(ValidationError, match="must not exceed"):
        Settings(context_max_skew_seconds=11, pending_ttl_seconds=10)


def test_settings_accept_cuda_backend_only_for_inference_server() -> None:
    settings = Settings(
        service_role="inference-server",
        model_backend="cuda-online-baseline",
        model_version="cuda-baseline-1.0.0",
    )

    assert settings.model_backend == "cuda-online-baseline"

    with pytest.raises(ValidationError, match="inference-server"):
        Settings(model_backend="cuda-online-baseline")
