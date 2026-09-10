"""Run reproducible lifecycle/offloading experiments and preserve raw observations."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib import request
import uuid


METHODS = ("always_on", "cold_on_demand", "cached_on_demand")
TIERS = ("nano", "agx", "spark")
PROMPT = "In one short sentence, explain why edge computing reduces latency."


def http_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 2400.0) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    req = request.Request(
        url,
        data=body,
        method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.resources: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def add(self, collection: list[dict[str, Any]], row: dict[str, Any]) -> None:
        with self.lock:
            collection.append(row)


class ResourceSampler:
    def __init__(self, proxy_url: str, recorder: Recorder, interval: float = 1.0) -> None:
        self.proxy_url = proxy_url.rstrip("/")
        self.recorder = recorder
        self.interval = interval
        self.context: dict[str, Any] = {}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self, **context: Any) -> None:
        self.context = context
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(5.0, self.interval * 3))

    def _run(self) -> None:
        while not self.stop_event.is_set():
            sampled_at = time.time()
            try:
                payload = http_json(f"{self.proxy_url}/metrics", timeout=5.0)
                for tier in TIERS:
                    node = payload.get("nodes", {}).get(tier, {})
                    self.recorder.add(
                        self.recorder.resources,
                        {
                            **self.context,
                            "timestamp": sampled_at,
                            "route": payload.get("route"),
                            "node": tier,
                            **node,
                        },
                    )
            except Exception as exc:
                self.recorder.add(
                    self.recorder.resources,
                    {
                        **self.context,
                        "timestamp": sampled_at,
                        "node": "collector",
                        "error": f"{type(exc).__name__}:{exc}",
                    },
                )
            self.stop_event.wait(self.interval)


def generate(
    proxy_url: str,
    recorder: Recorder,
    *,
    experiment: str,
    phase: str,
    method: str,
    concurrency: int,
    max_tokens: int,
    timeout: float,
    placement_mode: str = "dynamic",
    target_node: str | None = None,
) -> None:
    request_id = str(uuid.uuid4())
    submitted = time.time()
    try:
        response = http_json(
            f"{proxy_url.rstrip('/')}/generate",
            {
                "request_id": request_id,
                "prompt": PROMPT,
                "max_tokens": max_tokens,
                "concurrency": concurrency,
                "placement_mode": placement_mode,
                "target_node": target_node,
                "timeout_seconds": timeout,
            },
            timeout=timeout + 60.0,
        )
        placement = response["placement"]
        row = {
            "experiment": experiment,
            "phase": phase,
            "method": method,
            "requested_concurrency": concurrency,
            "status": "ok",
            **placement,
        }
    except Exception as exc:
        row = {
            "experiment": experiment,
            "phase": phase,
            "method": method,
            "requested_concurrency": concurrency,
            "request_id": request_id,
            "timestamp": submitted,
            "completed_timestamp": time.time(),
            "status": "error",
            "error": f"{type(exc).__name__}:{exc}",
        }
    recorder.add(recorder.requests, row)


def sustained(
    proxy_url: str,
    recorder: Recorder,
    *,
    experiment: str,
    phase: str,
    method: str,
    concurrency: int,
    duration: float,
    max_tokens: int,
    timeout: float,
    placement_mode: str = "dynamic",
) -> None:
    deadline = time.monotonic() + duration

    def client() -> None:
        while time.monotonic() < deadline:
            generate(
                proxy_url,
                recorder,
                experiment=experiment,
                phase=phase,
                method=method,
                concurrency=concurrency,
                max_tokens=max_tokens,
                timeout=timeout,
                placement_mode=placement_mode,
            )

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(client) for _ in range(concurrency)]
        for future in futures:
            future.result()


def configure(proxy_url: str, method: str, recorder: Recorder, experiment: str) -> dict[str, Any]:
    started = time.time()
    result = http_json(f"{proxy_url.rstrip('/')}/method", {"method": method})
    recorder.add(
        recorder.events,
        {
            "experiment": experiment,
            "phase": "setup",
            "method": method,
            "timestamp": started,
            "event": "method_setup",
            "details": result,
        },
    )
    return result


def capture_events(proxy_url: str, recorder: Recorder, experiment: str, method: str, since: float) -> None:
    for endpoint in ("activations", "state-transitions"):
        try:
            for event in http_json(f"{proxy_url.rstrip('/')}/{endpoint}", timeout=10.0):
                if float(event.get("timestamp") or 0.0) >= since:
                    recorder.add(
                        recorder.events,
                        {"experiment": experiment, "method": method, "source": endpoint, **event},
                    )
        except Exception as exc:
            recorder.add(
                recorder.events,
                {
                    "experiment": experiment,
                    "method": method,
                    "source": endpoint,
                    "timestamp": time.time(),
                    "event": "capture_error",
                    "error": f"{type(exc).__name__}:{exc}",
                },
            )


def measured_phase(
    args: argparse.Namespace,
    recorder: Recorder,
    experiment: str,
    method: str,
    body: Any,
) -> None:
    print(json.dumps({"event": "phase_setup", "experiment": experiment, "method": method}), flush=True)
    configure(args.proxy_url, method, recorder, experiment)
    started = time.time()
    sampler = ResourceSampler(args.proxy_url, recorder, args.sample_interval)
    sampler.start(experiment=experiment, phase="measurement", method=method)
    try:
        body()
    finally:
        sampler.stop()
        capture_events(args.proxy_url, recorder, experiment, method, started)
        write_csv(args.output_dir / "requests.csv", recorder.requests)
        write_csv(args.output_dir / "resources.csv", recorder.resources)
        write_csv(args.output_dir / "events.csv", recorder.events)
        print(
            json.dumps(
                {
                    "event": "phase_complete",
                    "experiment": experiment,
                    "method": method,
                    "requests": len(recorder.requests),
                    "resource_samples": len(recorder.resources),
                }
            ),
            flush=True,
        )


def run(args: argparse.Namespace) -> Recorder:
    recorder = Recorder()
    selected = set(args.experiments.split(","))
    enabled_methods = set(args.methods.split(","))

    def methods(order: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(method for method in order if method in enabled_methods)

    if "idle" in selected:
        for method in methods(("cached_on_demand", "always_on", "cold_on_demand")):
            measured_phase(args, recorder, "idle", method, lambda: time.sleep(args.idle_seconds))

    if "single" in selected:
        for method in methods(("always_on", "cold_on_demand", "cached_on_demand")):
            measured_phase(
                args,
                recorder,
                "single",
                method,
                lambda method=method: generate(
                    args.proxy_url,
                    recorder,
                    experiment="single",
                    phase="concurrency_1",
                    method=method,
                    concurrency=1,
                    max_tokens=args.max_tokens,
                    timeout=args.timeout,
                ),
            )

    if "activation" in selected:
        for method in methods(("cold_on_demand", "cached_on_demand")):
            for tier in ("agx", "spark"):
                experiment = f"activation_{tier}"
                measured_phase(
                    args,
                    recorder,
                    experiment,
                    method,
                    lambda method=method, tier=tier, experiment=experiment: generate(
                        args.proxy_url,
                        recorder,
                        experiment=experiment,
                        phase="first_offload",
                        method=method,
                        concurrency=1,
                        max_tokens=args.max_tokens,
                        timeout=args.timeout,
                        placement_mode="static",
                        target_node=tier,
                    ),
                )

    if "increasing" in selected:
        for method in methods(("cold_on_demand", "cached_on_demand", "always_on")):
            def increasing(method: str = method) -> None:
                for concurrency in args.concurrency:
                    sustained(
                        args.proxy_url,
                        recorder,
                        experiment="increasing",
                        phase=f"concurrency_{concurrency}",
                        method=method,
                        concurrency=concurrency,
                        duration=args.stage_seconds,
                        max_tokens=args.max_tokens,
                        timeout=args.timeout,
                    )
            measured_phase(args, recorder, "increasing", method, increasing)

        if "always_on" in enabled_methods:
            measured_phase(
                args,
                recorder,
                "nano_only",
                "always_on",
                lambda: [
                sustained(
                    args.proxy_url,
                    recorder,
                    experiment="nano_only",
                    phase=f"concurrency_{concurrency}",
                    method="always_on",
                    concurrency=concurrency,
                    duration=args.stage_seconds,
                    max_tokens=args.max_tokens,
                    timeout=args.timeout,
                    placement_mode="nano_only",
                )
                for concurrency in args.concurrency
                ],
            )

    if "burst" in selected:
        segments = ((1, 30.0), (16, 30.0), (2, 60.0))
        for method in methods(("cached_on_demand", "cold_on_demand", "always_on")):
            def burst(method: str = method) -> None:
                for index, (concurrency, duration) in enumerate(segments, 1):
                    sustained(
                        args.proxy_url,
                        recorder,
                        experiment="burst",
                        phase=f"segment_{index}_c{concurrency}",
                        method=method,
                        concurrency=concurrency,
                        duration=duration,
                        max_tokens=args.max_tokens,
                        timeout=args.timeout,
                    )
            measured_phase(args, recorder, "burst", method, burst)

    if "repeated" in selected:
        segments = ((1, args.low_seconds), (16, args.high_seconds), (1, args.low_seconds),
                    (16, args.high_seconds), (1, args.low_seconds))
        for method in methods(("cold_on_demand", "always_on", "cached_on_demand")):
            def repeated(method: str = method) -> None:
                for index, (concurrency, duration) in enumerate(segments, 1):
                    sustained(
                        args.proxy_url,
                        recorder,
                        experiment="repeated",
                        phase=f"segment_{index}_c{concurrency}",
                        method=method,
                        concurrency=concurrency,
                        duration=duration,
                        max_tokens=args.max_tokens,
                        timeout=args.timeout,
                    )
            measured_phase(args, recorder, "repeated", method, repeated)
    return recorder


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value
                 for key, value in row.items()}
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy-url", default="http://192.168.0.56:18101")
    parser.add_argument("--experiments", default="idle,single,activation,increasing,burst,repeated")
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--idle-seconds", type=float, default=300.0)
    parser.add_argument("--stage-seconds", type=float, default=15.0)
    parser.add_argument("--low-seconds", type=float, default=35.0)
    parser.add_argument("--high-seconds", type=float, default=20.0)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--concurrency", type=lambda text: tuple(int(item) for item in text.split(",")), default=(1, 2, 4, 8, 16, 32))
    parser.add_argument("--max-tokens", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()
    recorder = run(args)
    write_csv(args.output_dir / "requests.csv", recorder.requests)
    write_csv(args.output_dir / "resources.csv", recorder.resources)
    write_csv(args.output_dir / "events.csv", recorder.events)
    (args.output_dir / "run-config.json").write_text(
        json.dumps(vars(args), default=str, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"requests": len(recorder.requests), "resource_samples": len(recorder.resources), "events": len(recorder.events)}))


if __name__ == "__main__":
    main()
