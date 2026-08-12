import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error


sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_test  # noqa: E402


NOW_NS = 2_000_000_000_000_000_000


def reading(name, value="1", value_type="Int32"):
    return {
        "resourceName": name,
        "valueType": value_type,
        "value": value,
    }


def event(source, resources, *, origin=NOW_NS):
    return {
        "deviceName": smoke_test.DEVICE_NAME,
        "sourceName": source,
        "origin": origin,
        "readings": [reading(name) for name in resources],
    }


def complete_response(*, origin=NOW_NS):
    return {
        "events": [
            event(source, resources, origin=origin)
            for source, resources in smoke_test.EXPECTED_RESOURCES.items()
        ]
    }


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class EventValidationTests(unittest.TestCase):
    def test_accepts_collective_recent_typed_sources(self):
        response = complete_response()
        response["events"].reverse()

        smoke_test.validate_events(response, 10, now_ns=NOW_NS)

    def test_rejects_missing_source(self):
        response = complete_response()
        response["events"] = [
            item
            for item in response["events"]
            if item["sourceName"] != "magnetic"
        ]

        with self.assertRaisesRegex(
            smoke_test.SmokeFailure, "missing telemetry sources: magnetic"
        ):
            smoke_test.validate_events(response, 10, now_ns=NOW_NS)

    def test_rejects_stale_source(self):
        response = complete_response()
        for item in response["events"]:
            if item["sourceName"] == "temperature":
                item["origin"] = NOW_NS - 11_000_000_000

        with self.assertRaisesRegex(
            smoke_test.SmokeFailure, "stale telemetry sources: temperature"
        ):
            smoke_test.validate_events(response, 10, now_ns=NOW_NS)

    def test_rejects_missing_or_non_integer_readings(self):
        cases = {
            "missing resource": [reading("x"), reading("y")],
            "wrong value type": [
                reading("x"),
                reading("y"),
                reading("z", value_type="Float64"),
            ],
            "non-integer value": [
                reading("x"),
                reading("y"),
                reading("z", value="1.5"),
            ],
        }
        for label, readings in cases.items():
            with self.subTest(label=label):
                response = complete_response()
                acceleration = next(
                    item
                    for item in response["events"]
                    if item["sourceName"] == "acceleration"
                )
                acceleration["readings"] = readings
                with self.assertRaisesRegex(
                    smoke_test.SmokeFailure,
                    "malformed telemetry sources: acceleration",
                ):
                    smoke_test.validate_events(response, 10, now_ns=NOW_NS)


class UrlAndRetrievalTests(unittest.TestCase):
    def test_constructs_exact_read_only_urls(self):
        self.assertEqual(
            smoke_test.profile_url("http://metadata:59881/"),
            "http://metadata:59881/api/v3/deviceprofile/name/etri-uno-mqtt",
        )
        self.assertEqual(
            smoke_test.device_url("http://metadata:59881"),
            "http://metadata:59881/api/v3/device/name/arduino-001",
        )
        self.assertEqual(
            smoke_test.events_url("http://data:59880/"),
            "http://data:59880/api/v3/event/device/name/arduino-001?limit=20",
        )

    def test_verify_gets_profile_device_then_core_data(self):
        urls = []
        now_ns = __import__("time").time_ns()

        def getter(url):
            urls.append(url)
            if "/deviceprofile/" in url:
                return {"profile": {"name": smoke_test.PROFILE_NAME}}
            if "/device/name/" in url and "/event/" not in url:
                return {"device": {"name": smoke_test.DEVICE_NAME}}
            return complete_response(origin=now_ns)

        smoke_test.verify(
            "http://metadata:59881/",
            "http://data:59880/",
            0,
            60,
            json_getter=getter,
        )

        self.assertEqual(
            urls,
            [
                "http://metadata:59881/api/v3/deviceprofile/name/etri-uno-mqtt",
                "http://metadata:59881/api/v3/device/name/arduino-001",
                "http://data:59880/api/v3/event/device/name/arduino-001?limit=20",
            ],
        )

    def test_get_json_uses_get_request(self):
        seen = {}

        def opener(request, timeout):
            seen["method"] = request.get_method()
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            return FakeResponse(json.dumps({"events": []}).encode())

        payload = smoke_test.get_json(
            "http://data:59880/api/v3/event/device/name/arduino-001?limit=20",
            timeout=1.5,
            opener=opener,
        )

        self.assertEqual(payload, {"events": []})
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["timeout"], 1.5)


class PollingTests(unittest.TestCase):
    def test_polling_succeeds_after_all_sources_arrive(self):
        responses = [{"events": []}, complete_response()]
        clock = FakeClock()
        urls = []

        def getter(url):
            urls.append(url)
            return responses.pop(0)

        smoke_test.poll_for_telemetry(
            "http://data:59880",
            5,
            10,
            json_getter=getter,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            wall_time_ns=lambda: NOW_NS,
        )

        self.assertEqual(len(urls), 2)
        self.assertEqual(clock.sleeps, [1.0])

    def test_polling_retries_safe_get_failure(self):
        responses = [
            smoke_test.SmokeFailure("EdgeX GET failed with HTTP status 503"),
            complete_response(),
        ]
        clock = FakeClock()

        def getter(url):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        smoke_test.poll_for_telemetry(
            "http://data:59880",
            5,
            10,
            json_getter=getter,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            wall_time_ns=lambda: NOW_NS,
        )

        self.assertEqual(clock.sleeps, [1.0])

    def test_polling_stops_at_timeout(self):
        clock = FakeClock()
        calls = []

        def getter(url):
            calls.append(url)
            return {"events": []}

        with self.assertRaisesRegex(
            smoke_test.SmokeFailure, "telemetry polling timed out"
        ):
            smoke_test.poll_for_telemetry(
                "http://data:59880",
                2,
                10,
                json_getter=getter,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
                wall_time_ns=lambda: NOW_NS,
            )

        self.assertEqual(clock.value, 2.0)
        self.assertEqual(len(calls), 2)


class SafeErrorTests(unittest.TestCase):
    def test_http_error_does_not_leak_url_reason_or_body(self):
        secret_url = "http://user:password@metadata/private"
        secret_body = b"token=top-secret"

        def opener(request, timeout):
            raise urllib.error.HTTPError(
                secret_url,
                503,
                "upstream secret detail",
                {},
                io.BytesIO(secret_body),
            )

        with self.assertRaises(smoke_test.SmokeFailure) as raised:
            smoke_test.get_json(secret_url, opener=opener)

        message = str(raised.exception)
        self.assertEqual(message, "EdgeX GET failed with HTTP status 503")
        self.assertNotIn("password", message)
        self.assertNotIn("top-secret", message)
        self.assertNotIn("upstream", message)

    def test_cli_failure_prints_only_safe_failure(self):
        output = io.StringIO()
        with mock.patch.object(
            smoke_test,
            "verify",
            side_effect=smoke_test.SmokeFailure(
                "EdgeX GET failed with HTTP status 401"
            ),
        ), contextlib.redirect_stdout(output):
            status = smoke_test.main([])

        self.assertEqual(status, 1)
        self.assertEqual(
            output.getvalue(),
            "FAIL: EdgeX GET failed with HTTP status 401\n",
        )


class CliTests(unittest.TestCase):
    def test_cli_accepts_endpoint_timeout_and_freshness_flags(self):
        args = smoke_test.build_parser().parse_args(
            [
                "--metadata-url",
                "http://metadata",
                "--data-url",
                "http://data",
                "--timeout",
                "7.5",
                "--freshness-seconds",
                "42",
            ]
        )

        self.assertEqual(args.metadata_url, "http://metadata")
        self.assertEqual(args.data_url, "http://data")
        self.assertEqual(args.timeout, 7.5)
        self.assertEqual(args.freshness_seconds, 42.0)


if __name__ == "__main__":
    unittest.main()
