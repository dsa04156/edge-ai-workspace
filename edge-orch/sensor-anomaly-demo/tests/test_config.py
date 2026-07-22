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
