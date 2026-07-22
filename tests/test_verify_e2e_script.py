from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "tools" / "verify_e2e.sh").read_text(encoding="utf-8")


def test_verify_e2e_uses_current_device_service_selectors():
    assert "app.kubernetes.io/name=device-serial-jetson" in SCRIPT
    assert "app.kubernetes.io/name=device-sensehat-raspi" in SCRIPT
    assert "app=device-serial-jetson" not in SCRIPT


def test_verify_e2e_covers_current_virtual_device_inventory():
    expected_devices = {
        "virtual-temperature-001",
        "virtual-light-001",
        "virtual-magnetic-001",
        "virtual-acceleration-x-001",
        "virtual-acceleration-y-001",
        "virtual-acceleration-z-001",
        "env-sensehat-temperature-01",
        "env-sensehat-humidity-01",
        "env-sensehat-pressure-01",
        "imu-sensehat-compass-01",
        "imu-sensehat-orientation-01",
        "imu-sensehat-gyroscope-01",
    }

    for device_name in expected_devices:
        assert device_name in SCRIPT


def test_verify_e2e_describes_current_cache_and_storage_contract():
    expected_contract = (
        "device-serial-jetson.edgex-edge.svc.cluster.local:59910",
        "device-sensehat-raspi.edgex-edge.svc.cluster.local:59911",
        "/api/v3/localdata/stats",
        "10 minutes",
        "10,000 samples",
        "64 MiB",
        "Core Data/PostgreSQL",
        "No SQLite outbox or offline replay",
    )

    for contract in expected_contract:
        assert contract in SCRIPT

    assert "only one volatile latest value" not in SCRIPT
    assert "not a recent-window cache" not in SCRIPT


def test_verify_e2e_reads_back_both_protocols_from_core_data():
    assert "edgex-core-data:59880" in SCRIPT
    assert "event/device/name/virtual-temperature-001?limit=1" in SCRIPT
    assert "event/device/name/env-sensehat-humidity-01?limit=1" in SCRIPT


def test_verify_e2e_checks_recovery_control_plane_restoration():
    expected_checks = (
        "application edgex-telemetry",
        ".spec.syncPolicy.automated.selfHeal",
        "app.kubernetes.io/name=edgex-messagebus",
        "daemonset edgemesh-agent",
    )

    for check in expected_checks:
        assert check in SCRIPT
