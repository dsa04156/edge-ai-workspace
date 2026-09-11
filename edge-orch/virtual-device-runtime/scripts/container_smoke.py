"""Verify an already-built Docker image; only creates/removes its own containers."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def docker(*args):
    return subprocess.check_output(["rtk", "proxy", "docker", *args], text=True).strip()


def call(base, path, body=None):
    request = Request(base + path, data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def scenario(image, missing=False):
    name = "vd-smoke-" + uuid.uuid4().hex[:12]
    args = ["run", "-d", "--name", name, "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "256m", "--cpus", "1",
            "--pids-limit", "64", "-p", "127.0.0.1::8080", "-e", "POD_UID=local-container-test"]
    if missing:
        args += ["-e", "MODEL_PATH=/missing/model.json"]
    container_id = docker(*args, image)
    try:
        details = json.loads(docker("inspect", container_id))[0]
        port = int(details["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"])
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 15
        while True:
            try:
                if call(base, "/healthz")[0] == 200:
                    break
            except (OSError, URLError):
                pass
            assert time.monotonic() < deadline, docker("logs", container_id)
            time.sleep(.1)
        assert details["Config"]["User"] == "10001:10001"
        assert call(base, "/readyz")[0] == (503 if missing else 200)
        payload = {"requestId": "docker-infer-1", "clientId": "local-container-smoke",
                   "features": [5.1, 3.5, 1.4, .2]}
        code, result = call(base, "/infer", payload)
        if missing:
            assert code == 503
            status = call(base, "/status")[1]
            assert status["modelReady"] is False and status["succeeded"] == 0
            assert "model_load_failed" in status["error"]
        else:
            assert code == 200 and result["result"]["label"] == "setosa"
            status = call(base, "/status")[1]
            assert status["lastSuccess"] == result and status["succeeded"] == 1
            assert status["inFlight"] == status["failed"] == 0
            assert result["virtualDeviceId"] == "vd-demo-001"
            assert result["requestId"] == payload["requestId"]
            assert call(base, "/infer", {**payload, "features": [1]})[0] == 422
            assert call(base, "/status")[1]["rejected"] == 1
        docker("stop", "--time", "35", container_id)
        stopped = json.loads(docker("inspect", container_id))[0]["State"]
        assert not stopped["Running"] and not stopped["OOMKilled"]
        assert stopped["ExitCode"] in (0, 143)
        with socket.socket() as sock:
            sock.settimeout(1)
            assert sock.connect_ex(("127.0.0.1", port)) != 0
        return {"scenario": "missing_model" if missing else "inference",
                "containerId": container_id, "status": status,
                "exitCode": stopped["ExitCode"], "stoppedAndPortClosed": True}
    finally:
        docker("rm", "-f", container_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    registry = Path(__file__).resolve().parents[2] / "state-aggregator/app/config/virtual_devices.json"
    before = hashlib.sha256(registry.read_bytes()).hexdigest()
    image_info = json.loads(docker("image", "inspect", args.image))[0]
    results = [scenario(args.image), scenario(args.image, missing=True)]
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before
    report = {"image": args.image, "imageId": image_info["Id"], "architecture": image_info["Architecture"],
              "registryUnchanged": True, "scenarios": results,
              "scope": "local Docker only; injected Pod UID is not Kubernetes evidence"}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"imageId": report["imageId"], "scenariosPassed": len(results),
                      "registryUnchanged": True, "report": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
