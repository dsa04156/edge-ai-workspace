from datetime import datetime, timezone
import pytest
from app.ai_input import common_ai_request
from app.models import EdgeXDevice, TelemetryPoint


def test_edgex_adapter_preserves_reading_identity_units_and_nanoseconds():
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    device = EdgeXDevice(name="sensor", profile_name="profile", device_service_name="serial",
                         admin_state="UNLOCKED", operating_state="UP")
    point = TelemetryPoint(device_name="sensor", source_name="temperature", resource_name="temperature_raw",
                           value_type="Int32", value=354, timestamp=now, origin=1789344000000000001,
                           event_id="event", units="raw")
    def adapt(): return common_ai_request(device, point, service_id="llama", request_id="request", now=now)
    result = adapt()
    assert result["source"]["origin_ns"] == "1789344000000000001"
    assert result["input"]["data"]["measurements"] == [{"name": "temperature_raw", "value": 354, "unit": "raw"}]
    point.units = None
    with pytest.raises(ValueError, match="unit"): adapt()
    point.units = "raw"
    point.timestamp = datetime(2026, 9, 13, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="fresh"): adapt()
    point.timestamp = now
    point.device_name = "another-sensor"
    with pytest.raises(ValueError, match="identity"): adapt()


def test_consumer_deduplicates_events_across_restart_and_separates_service_uids():
    import asyncio
    import copy
    import json
    import httpx
    from app.ai_input import EdgeXAIConsumer
    async def run():
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        device = EdgeXDevice(name="sensor", profile_name="profile", device_service_name="serial",
                             admin_state="UNLOCKED", operating_state="UP")
        point = TelemetryPoint(device_name="sensor", source_name="temperature", resource_name="temperature_raw",
            value_type="Int32", value=354, timestamp=now, origin=1789344000000000001, event_id="event", units="raw")
        class Reader:
            async def get_devices(self): return [device]
            async def get_latest_event(self, name):
                assert name == "sensor"
                return [point]
        config = {"service": {"version": "a" * 64}, "max_tokens": 64, "offload": {"enabled": True},
            "input": {"device_id": "sensor", "profile_id": "profile", "resource_name": "temperature_raw", "poll_seconds": 5}}
        states = [{"name": name, "uid": name + "-uid", "serving": True, "checkedAt": now.timestamp(), "commonAI": copy.deepcopy(config)}
                  for name in ["one", "two"]]
        records, posts = {}, []
        async def handle(request):
            if request.url.path == "/services":
                return httpx.Response(200, json={"services": states, "lastError": None, "snapshotAgeSeconds": 0})
            if request.method == "GET":
                return httpx.Response(200 if request.url.path in records else 404, json={})
            body = json.loads(request.content)
            posts.append(body)
            assert request.headers["x-runtime-service-uid"] == body["service_id"] + "-uid"
            records[request.url.path.replace("/invoke", "/requests/" + body["request_id"])] = True
            return httpx.Response(200, json={"result": {"status": "success"}, "execution": {"node": "edge"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            def consumer(): return EdgeXAIConsumer(Reader(), client, "http://gateway", clock=now.timestamp)
            first = consumer()
            assert len(await first.tick()) == 2 and len(posts) == 2
            assert posts[0]["request_id"] != posts[1]["request_id"]
            await first.tick()
            assert len(posts) == 2
            restarted = consumer()
            assert all(r["status"] == "already_recorded" for r in await restarted.tick())
            assert len(posts) == 2
            states[0]["serving"] = False
            states[1]["checkedAt"] -= 20
            assert await consumer().tick() == []
            assert len(posts) == 2
    asyncio.run(run())
