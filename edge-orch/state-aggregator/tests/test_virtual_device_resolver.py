from datetime import datetime, timedelta, timezone
import pytest

from app.models import EdgeXDevice, EdgeXDeviceProfile, EdgeXDeviceResource, EventHistoryPage, TelemetryPoint
from app.virtual_device_bindings import VirtualDeviceBindingConfig
from app.virtual_device_resolver import resolve_virtual_device


def _instance():
    return VirtualDeviceBindingConfig.model_validate({"apiVersion":"virtual-device-binding/v1","instances":[{"id":"v","physicalDeviceRef":{"name":"d","expectedProfileName":"p"},"capabilities":[{"id":"c","freshnessSeconds":90,"inputs":[{"inputId":"i","capabilityField":"x","required":True,"bindings":[{"sourceName":"s","resourceName":"r"}],"acceptedValueTypes":["Float64"],"acceptedUnits":["g"]}]}],"aiServiceRef":{"serviceId":"a","inputContract":"a/v1","bindingMode":"declarative_read_only","inputFieldMap":[{"inputId":"i","aiField":"ai_x"}]}}]}).instances[0]


def test_resolver_ready_preserves_ai_map_and_complete_provenance():
    now = datetime.now(timezone.utc)
    point = TelemetryPoint(device_name="d", source_name="s", resource_name="r", value_type="Float64", value=1.0, timestamp=now, origin=2, event_id="e", event_origin=1, reading_origin=2, profile_name="p", units="g")
    view = resolve_virtual_device(_instance(), config_revision="r", observation_time=now, device=EdgeXDevice(name="d", profile_name="p", device_service_name="svc", admin_state="UNLOCKED", operating_state="UP"), profile=EdgeXDeviceProfile(name="p", device_resources=[EdgeXDeviceResource(name="r")]), history=EventHistoryPage(total_count=1, events=[point]))
    assert view.binding_status == "ready"
    assert view.ai_service_ref.input_field_map[0].ai_field == "ai_x"
    assert view.capabilities[0].inputs[0].original_event_ref.event_id == "e"


def test_resolver_precedence_and_optional_warning_are_deterministic():
    now = datetime.now(timezone.utc)
    view = resolve_virtual_device(_instance(), config_revision="r", observation_time=now, device=None, profile=None, history=None)
    assert view.binding_status == "unresolved"
    assert view.reason_codes == ["device_missing"]
    assert view.capabilities[0].inputs[0].ready is False

@pytest.mark.parametrize(
    ("admin_state", "operating_state", "history", "expected"),
    [
        ("LOCKED", "UP", EventHistoryPage(total_count=0), "edgex_admin_locked"),
        ("UNKNOWN", "UP", EventHistoryPage(total_count=0), "edgex_admin_unknown"),
        ("UNLOCKED", "DOWN", EventHistoryPage(total_count=0), "edgex_operating_down"),
        ("UNLOCKED", "UNKNOWN", EventHistoryPage(total_count=0), "edgex_operating_unknown"),
        ("UNLOCKED", "UP", EventHistoryPage(total_count=0), "no_event"),
        (
            "UNLOCKED",
            "UP",
            EventHistoryPage(
                total_count=10,
                history_truncated=True,
                uncertain_source_resources=[("s", "r")],
            ),
            "history_truncated",
        ),
    ],
)
def test_resolver_lattice_state_and_history_branches(
    admin_state, operating_state, history, expected
):
    now = datetime.now(timezone.utc)
    view = resolve_virtual_device(
        _instance(), config_revision="revision", observation_time=now,
        device=EdgeXDevice(
            name="d", profile_name="p", device_service_name="svc",
            admin_state=admin_state, operating_state=operating_state,
        ),
        profile=EdgeXDeviceProfile(name="p", device_resources=[EdgeXDeviceResource(name="r")]),
        history=history,
    )
    assert view.binding_status == "degraded"
    assert expected in view.reason_codes


def test_resolver_identity_failure_does_not_leak_input_reasons():
    now = datetime.now(timezone.utc)
    view = resolve_virtual_device(
        _instance(), config_revision="revision", observation_time=now,
        device=EdgeXDevice(
            name="d", profile_name="wrong", device_service_name="svc",
            admin_state="LOCKED", operating_state="DOWN",
        ),
        profile=EdgeXDeviceProfile(name="wrong", device_resources=[]),
        history=EventHistoryPage(total_count=0, history_truncated=True),
    )
    assert view.binding_status == "unresolved"
    assert view.reason_codes == ["profile_mismatch"]
    assert view.capabilities[0].inputs[0].ready is False

def test_resolver_uses_prior_probe_to_distinguish_stale_from_missing():
    now = datetime.now(timezone.utc)
    stale_point = TelemetryPoint(
        device_name="d",
        source_name="s",
        resource_name="r",
        value_type="Float64",
        value=1.0,
        timestamp=now - timedelta(seconds=120),
        origin=2,
        event_id="stale-event",
        event_origin=1,
        reading_origin=2,
        profile_name="p",
        units="g",
    )

    view = resolve_virtual_device(
        _instance(),
        config_revision="revision",
        observation_time=now,
        device=EdgeXDevice(
            name="d",
            profile_name="p",
            device_service_name="svc",
            admin_state="UNLOCKED",
            operating_state="UP",
        ),
        profile=EdgeXDeviceProfile(
            name="p",
            device_resources=[EdgeXDeviceResource(name="r")],
        ),
        history=EventHistoryPage(
            total_count=0,
            prior_probe_events=[stale_point],
        ),
    )

    assert view.binding_status == "degraded"
    assert view.reason_codes == ["stale"]


def test_resolver_prefers_configured_alias_order_before_recency():
    now = datetime.now(timezone.utc)
    document = _instance().model_dump(mode="json", by_alias=True)
    configured_input = document["capabilities"][0]["inputs"][0]
    configured_input["bindings"].append(
        {"sourceName": "new-source", "resourceName": "new-resource"}
    )
    instance = VirtualDeviceBindingConfig.model_validate(
        {
            "apiVersion": "virtual-device-binding/v1",
            "instances": [document],
        }
    ).instances[0]
    primary = TelemetryPoint(
        device_name="d",
        source_name="s",
        resource_name="r",
        value_type="Float64",
        value=1.0,
        timestamp=now - timedelta(seconds=5),
        origin=2,
        event_id="primary",
        event_origin=1,
        reading_origin=2,
        profile_name="p",
        units="g",
    )
    secondary = TelemetryPoint(
        device_name="d",
        source_name="new-source",
        resource_name="new-resource",
        value_type="Float64",
        value=9.0,
        timestamp=now,
        origin=4,
        event_id="secondary",
        event_origin=3,
        reading_origin=4,
        profile_name="p",
        units="g",
    )

    view = resolve_virtual_device(
        instance,
        config_revision="revision",
        observation_time=now,
        device=EdgeXDevice(
            name="d",
            profile_name="p",
            device_service_name="svc",
            admin_state="UNLOCKED",
            operating_state="UP",
        ),
        profile=EdgeXDeviceProfile(
            name="p",
            device_resources=[
                EdgeXDeviceResource(name="r"),
                EdgeXDeviceResource(name="new-resource"),
            ],
        ),
        history=EventHistoryPage(total_count=2, events=[secondary, primary]),
    )

    projected_input = view.capabilities[0].inputs[0]
    assert view.binding_status == "ready"
    assert projected_input.selected_source_name == "s"
    assert projected_input.value == 1.0


def _resolve_points(
    now: datetime,
    points: list[TelemetryPoint],
    *,
    resources: list[str] | None = None,
):
    return resolve_virtual_device(
        _instance(),
        config_revision="revision",
        observation_time=now,
        device=EdgeXDevice(
            name="d",
            profile_name="p",
            device_service_name="svc",
            admin_state="UNLOCKED",
            operating_state="UP",
        ),
        profile=EdgeXDeviceProfile(
            name="p",
            device_resources=[
                EdgeXDeviceResource(name=name) for name in (resources or ["r"])
            ],
        ),
        history=EventHistoryPage(total_count=len(points), events=points),
    )


def _ready_point(now: datetime, **updates) -> TelemetryPoint:
    point = TelemetryPoint(
        device_name="d",
        source_name="s",
        resource_name="r",
        value_type="Float64",
        value=1.0,
        timestamp=now,
        origin=2,
        event_id="event",
        event_origin=1,
        reading_origin=2,
        profile_name="p",
        units="g",
    )
    return point.model_copy(update=updates)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"value_type": "String"}, "type_mismatch"),
        ({"units": "m/s2"}, "unit_mismatch"),
        ({"event_id": None}, "provenance_incomplete"),
        ({"source_name": ""}, "provenance_incomplete"),
        ({"resource_name": ""}, "provenance_incomplete"),
    ],
)
def test_resolver_rejects_incompatible_or_incomplete_inputs(updates, reason):
    now = datetime.now(timezone.utc)
    view = _resolve_points(now, [_ready_point(now, **updates)])

    assert view.binding_status == "degraded"
    assert reason in view.reason_codes
    if reason == "provenance_incomplete":
        assert view.capabilities[0].inputs[0].original_event_ref is None


def test_resolver_reports_profile_resource_missing():
    now = datetime.now(timezone.utc)
    view = _resolve_points(now, [_ready_point(now)], resources=["other"])

    assert view.binding_status == "degraded"
    assert view.reason_codes == [
        "profile_resource_missing",
        "required_input_missing",
    ]


def test_resolver_detects_equal_provenance_value_conflict():
    now = datetime.now(timezone.utc)
    first = _ready_point(now, event_id="same-event", value=1.0)
    conflicting = _ready_point(now, event_id="same-event", value=2.0)

    view = _resolve_points(now, [conflicting, first])

    assert view.binding_status == "degraded"
    assert view.reason_codes == ["ambiguous_binding"]
    assert view.capabilities[0].inputs[0].value is None

@pytest.mark.parametrize("reverse", [False, True])
def test_resolver_detects_equal_rank_metadata_conflict_in_any_order(reverse):
    now = datetime.now(timezone.utc)
    first = _ready_point(now, event_id="same-event", value=1.0)
    conflicting = first.model_copy(update={"units": "m/s2"})
    points = [first, conflicting] if reverse else [conflicting, first]

    view = _resolve_points(now, points)

    assert view.binding_status == "degraded"
    assert view.reason_codes == ["ambiguous_binding"]
    assert view.capabilities[0].inputs[0].value is None


def test_resolver_uses_lexical_event_id_as_final_tiebreak():
    now = datetime.now(timezone.utc)
    lexical_first = _ready_point(now, event_id="a", value=1.0)
    lexical_second = _ready_point(now, event_id="b", value=2.0)

    view = _resolve_points(now, [lexical_second, lexical_first])

    assert view.binding_status == "ready"
    assert (
        view.capabilities[0].inputs[0].original_event_ref.event_id
        == "a"
    )


def test_truncated_history_never_reports_ready_with_a_visible_candidate():
    now = datetime.now(timezone.utc)
    view = resolve_virtual_device(
        _instance(),
        config_revision="revision",
        observation_time=now,
        device=EdgeXDevice(
            name="d",
            profile_name="p",
            device_service_name="svc",
            admin_state="UNLOCKED",
            operating_state="UP",
        ),
        profile=EdgeXDeviceProfile(
            name="p",
            device_resources=[EdgeXDeviceResource(name="r")],
        ),
        history=EventHistoryPage(
            total_count=2,
            events=[_ready_point(now)],
            history_truncated=True,
            uncertain_source_resources=[("s", "r")],
        ),
    )

    assert view.binding_status == "degraded"
    assert "history_truncated" in view.reason_codes


def test_whitespace_event_id_is_incomplete_provenance():
    now = datetime.now(timezone.utc)
    view = _resolve_points(now, [_ready_point(now, event_id=" ")])

    assert view.binding_status == "degraded"
    assert "provenance_incomplete" in view.reason_codes


def test_reading_after_fixed_observation_time_is_not_ready():
    now = datetime.now(timezone.utc)
    future = _ready_point(
        now,
        timestamp=now + timedelta(microseconds=1),
        reading_origin=3,
        origin=3,
    )
    view = _resolve_points(now, [future])

    assert view.binding_status == "degraded"
    assert "provenance_incomplete" in view.reason_codes
    assert view.capabilities[0].inputs[0].ready is False


def test_missing_profile_never_marks_input_ready():
    now = datetime.now(timezone.utc)
    view = resolve_virtual_device(
        _instance(),
        config_revision="revision",
        observation_time=now,
        device=EdgeXDevice(
            name="d",
            profile_name="p",
            device_service_name="svc",
            admin_state="UNLOCKED",
            operating_state="UP",
        ),
        profile=None,
        history=EventHistoryPage(
            total_count=1,
            events=[_ready_point(now)],
        ),
    )

    assert view.binding_status == "unresolved"
    assert view.reason_codes == ["profile_not_found"]
    assert view.capabilities[0].inputs[0].ready is False


def test_undeclared_primary_alias_cannot_override_declared_fallback():
    now = datetime.now(timezone.utc)
    document = _instance().model_dump(mode="json", by_alias=True)
    configured_input = document["capabilities"][0]["inputs"][0]
    configured_input["bindings"] = [
        {"sourceName": "primary", "resourceName": "undeclared"},
        {"sourceName": "s", "resourceName": "r"},
    ]
    instance = VirtualDeviceBindingConfig.model_validate(
        {
            "apiVersion": "virtual-device-binding/v1",
            "instances": [document],
        }
    ).instances[0]
    undeclared = _ready_point(
        now,
        source_name="primary",
        resource_name="",
        value=9.0,
    )
    fallback = _ready_point(
        now - timedelta(microseconds=1),
        value=1.0,
    )

    view = resolve_virtual_device(
        instance,
        config_revision="revision",
        observation_time=now,
        device=EdgeXDevice(
            name="d",
            profile_name="p",
            device_service_name="svc",
            admin_state="UNLOCKED",
            operating_state="UP",
        ),
        profile=EdgeXDeviceProfile(
            name="p",
            device_resources=[EdgeXDeviceResource(name="r")],
        ),
        history=EventHistoryPage(
            total_count=2,
            events=[undeclared, fallback],
        ),
    )

    projected = view.capabilities[0].inputs[0]
    assert view.binding_status == "ready"
    assert projected.selected_source_name == "s"
    assert projected.selected_resource_name == "r"
    assert projected.value == 1.0
    assert projected.ready is True
