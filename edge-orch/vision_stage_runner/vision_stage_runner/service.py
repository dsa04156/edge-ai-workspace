from __future__ import annotations

import os
import time
from typing import Callable

from fastapi import FastAPI, Query

from vision_stage_runner.main import (
    run_capture,
    run_inference,
    run_postprocess,
    run_preprocess,
    run_result_delivery,
)


SERVICE_NAME = os.getenv("SERVICE_NAME", "factory-vision-inspection-ai")
SCENARIO_ID = os.getenv("SCENARIO_ID", "jetson-vision-inspection")
TARGET_DEVICE = os.getenv("TARGET_DEVICE", "etri-dev0001-jetorn")

STAGE_RUNNERS: tuple[tuple[str, Callable[[str], dict]], ...] = (
    ("capture", run_capture),
    ("preprocess", run_preprocess),
    ("inference", run_inference),
    ("postprocess", run_postprocess),
    ("result_delivery", run_result_delivery),
)

app = FastAPI(title=SERVICE_NAME, version="1.0.0")


@app.get("/healthz")
def healthz() -> dict:
    return {
        "service": SERVICE_NAME,
        "scenario": SCENARIO_ID,
        "target_device": TARGET_DEVICE,
        "status": "healthy",
    }


@app.get("/inspect")
def inspect(
    workflow_id: str = Query(
        default="factory-vision-live",
        min_length=1,
        description="Deterministic workflow id for the inspection run.",
    )
) -> dict:
    stages: dict[str, dict] = {}
    started = time.perf_counter()

    for stage_name, runner in STAGE_RUNNERS:
        stage_started = time.perf_counter()
        result = runner(workflow_id)
        stages[stage_name] = {
            "elapsed_ms": round((time.perf_counter() - stage_started) * 1000, 3),
            "result": result,
        }

    return {
        "service": SERVICE_NAME,
        "scenario": SCENARIO_ID,
        "target_device": TARGET_DEVICE,
        "workflow_id": workflow_id,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "stages": stages,
        "resource_request": {
            "needed": True,
            "reason": ["gpu_inference_pressure", "cache_required"],
            "augmentation_mode": "observed-only",
        },
    }
