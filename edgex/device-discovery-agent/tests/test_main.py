import pytest

from app.main import _configured_protocols


def test_configured_protocols_are_normalized_and_deduplicated(monkeypatch):
    monkeypatch.setenv("DISCOVERY_PROTOCOLS", " Serial, i2c,serial ")

    assert _configured_protocols() == ("serial", "i2c")


def test_configured_protocols_reject_unknown_plugins(monkeypatch):
    monkeypatch.setenv("DISCOVERY_PROTOCOLS", "serial,bluetooth")

    with pytest.raises(RuntimeError, match="bluetooth"):
        _configured_protocols()
