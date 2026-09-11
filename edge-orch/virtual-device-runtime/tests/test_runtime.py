import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from vd_runtime.api import InferenceRequest, Runtime, create_app
from vd_runtime.model import NearestCentroid

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {"requestId": "jetson-test-1", "clientId": "etri-dev0001-jetorn", "features": [5.1, 3.5, 1.4, 0.2]}


def test_actual_inference_identity_and_counters(monkeypatch):
    monkeypatch.setenv("POD_UID", "pod-1")
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").json()["ready"] is True
        result = client.post("/infer", json=PAYLOAD).json()
        assert result["result"]["label"] == "setosa"
        other = client.post("/infer", json={**PAYLOAD, "requestId": "two", "features": [6.5, 3, 5.8, 2.2]}).json()
        assert other["result"]["label"] == "virginica"
        assert result["result"]["distances"] != other["result"]["distances"]
        status = client.get("/status").json()
        assert status["succeeded"] == 2 and status["failed"] == 0 and status["inFlight"] == 0
        assert status["lastSuccess"] == other
        assert result["podUid"] == status["podUid"] == "pod-1"
        assert result["bootId"] == status["bootId"]
        assert status["usage"]["memoryBytes"] > 0


@pytest.mark.parametrize("features", [[1], [1,2,3,4,5], [-1,2,3,4], [1,2,3,31], ["x",2,3,4], [True,2,3,4]])
def test_invalid_inputs_are_not_inference(features):
    with TestClient(create_app()) as client:
        assert client.post("/infer", json={**PAYLOAD, "features": features}).status_code == 422
        status = client.get("/status").json()
        assert status["succeeded"] == status["failed"] == status["inFlight"] == 0
        assert status["rejected"] == 1


@pytest.mark.parametrize("body", [
    b'{"requestId":"x","clientId":"y","features":[NaN,2,3,4]}',
    b'{"requestId":"x","clientId":"y","features":[Infinity,2,3,4]}',
    b'{"invalid":',
])
def test_nonfinite_and_invalid_json(body):
    with TestClient(create_app()) as client:
        assert client.post("/infer", content=body, headers={"Content-Type":"application/json"}).status_code == 422


def test_missing_model_is_alive_but_unready(monkeypatch):
    monkeypatch.setenv("MODEL_PATH", "/missing/model.json")
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        assert client.post("/infer", json=PAYLOAD).status_code == 503
        status = client.get("/status").json()
        assert status["modelReady"] is False and "model_load_failed" in status["error"]
        assert status["model"]["id"] is None


def test_corrupt_model(monkeypatch, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"algorithm":"unsupported"}')
    monkeypatch.setenv("MODEL_PATH", str(path))
    with TestClient(create_app()) as client:
        assert client.get("/readyz").status_code == 503


def test_model_error_latches_unready():
    class Broken(NearestCentroid):
        def infer(self, features):
            raise RuntimeError("model broke")
    with TestClient(create_app(Runtime(Broken(ROOT / "models/iris-centroids.json")))) as client:
        assert client.post("/infer", json=PAYLOAD).status_code == 503
        status = client.get("/status").json()
        assert status["failed"] == 1 and status["inFlight"] == 0
        assert status["lastProcessedAt"] and not status["modelReady"]
        assert client.get("/readyz").status_code == 503


def test_draining_rejects_new_work():
    runtime = Runtime()
    runtime.draining = True
    with TestClient(create_app(runtime)) as client:
        assert client.get("/readyz").status_code == 503
        assert client.post("/infer", json=PAYLOAD).status_code == 503
        assert runtime.in_flight == 0


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(.03)
    raise AssertionError("timed out waiting for local server")


def test_real_http_client_and_sigterm_drain(tmp_path):
    port = free_port()
    runner = tmp_path / "run.py"
    runner.write_text("""
import os, time, uvicorn
import vd_runtime.__main__ as entry
from vd_runtime.api import Runtime, create_app
from vd_runtime.model import NearestCentroid
from pathlib import Path
class SlowModel(NearestCentroid):
    def infer(self, features):
        time.sleep(0.6)
        return super().infer(features)
entry.app = create_app(Runtime(SlowModel(Path(os.environ["TEST_MODEL_PATH"]))))
entry.DrainingServer(uvicorn.Config(entry.app, host="127.0.0.1",
    port=int(os.environ["PORT"]), timeout_graceful_shutdown=25)).run()
""")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PORT": str(port), "POD_UID": "http-test-pod",
           "TEST_MODEL_PATH": str(ROOT / "models/iris-centroids.json")}
    url = f"http://127.0.0.1:{port}"
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(runner)], env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                wait_for(lambda: client.get(url + "/readyz").status_code == 200)
                completed = subprocess.run([sys.executable, str(ROOT / "scripts/jetson_client.py"),
                                            "--url", url, "--expected-label", "setosa"],
                                           capture_output=True, text=True, timeout=10)
                assert completed.returncode == 0, completed.stderr
                evidence = json.loads(completed.stdout)
                assert evidence["statusMatched"] and evidence["afterSucceeded"] == 1
                with ThreadPoolExecutor() as pool:
                    future = pool.submit(client.post, url + "/infer", json={**PAYLOAD, "requestId":"drain-me"})
                    wait_for(lambda: client.get(url + "/status").json()["inFlight"] == 1)
                    process.terminate()
                    response = future.result(timeout=5)
                    assert response.status_code == 200 and response.json()["requestId"] == "drain-me"
                assert process.wait(timeout=5) in (0, -15)
                with pytest.raises(httpx.ConnectError):
                    client.get(url + "/healthz")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
