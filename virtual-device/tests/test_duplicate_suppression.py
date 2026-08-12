from virtual_device.normalizer import SampleDecision, SampleGuard


def test_identical_timestamp_and_payload_is_duplicate() -> None:
    guard = SampleGuard()
    data = {"acceleration_x": {"value": 0.12, "unit": "g"}}

    assert guard.check(1710000000, data) is SampleDecision.NEW
    assert guard.check(1710000000, data) is SampleDecision.DUPLICATE


def test_same_value_with_newer_source_timestamp_is_new() -> None:
    guard = SampleGuard()
    data = {"acceleration_x": {"value": 0.12, "unit": "g"}}

    assert guard.check(1710000000, data) is SampleDecision.NEW
    assert guard.check(1710000001, data) is SampleDecision.NEW


def test_older_comparable_source_timestamp_is_stale() -> None:
    guard = SampleGuard()

    assert guard.check(1710000001, {"value": 1}) is SampleDecision.NEW
    assert guard.check(1710000000, {"value": 2}) is SampleDecision.STALE


def test_same_timestamp_with_corrected_payload_is_new() -> None:
    guard = SampleGuard()

    assert guard.check(1710000000, {"value": 1}) is SampleDecision.NEW
    assert guard.check(1710000000, {"value": 2}) is SampleDecision.NEW


def test_identical_payload_without_source_timestamp_is_duplicate() -> None:
    guard = SampleGuard()

    assert guard.check(None, {"value": 1}) is SampleDecision.NEW
    assert guard.check(None, {"value": 1}) is SampleDecision.DUPLICATE
