"""Isolated ordered-demo entrypoint using the platform's runtime executor/API."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from kubernetes import client, config

from .model_offload_api import create_model_offload_router
from .model_offload_contract import ModelOffloadContract
from .model_offload_controller import OffloadJournal, WorkerTransport
from .model_offload_ordered import OrderedModelOffloadExecutionController
from .model_offload_demo_run import OrderedDemoRun, create_demo_run_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await controller.start()
    try:
        yield
    finally:
        await runner.close()
        await controller.stop()


if os.getenv("MODEL_OFFLOAD_ENABLED") != "true" or not os.getenv("EXECUTION_MANAGEMENT_TOKEN"):
    raise ValueError("isolated_demo_requires_enable_and_execution_token")
contract = ModelOffloadContract.model_validate_json(Path(os.environ["MODEL_OFFLOAD_CONTRACT_PATH"]).read_text())
config.load_incluster_config()
kube = SimpleNamespace(enabled=True, v1=client.CoreV1Api())
controller = OrderedModelOffloadExecutionController(
    contract, OffloadJournal(Path(os.environ["DATA_DIR"]) / "ordered-runtime.sqlite3"),
    WorkerTransport(contract, kube),
)
app = FastAPI(title="Nano–Orin–Spark ordered demo", lifespan=lifespan)
app.include_router(create_model_offload_router(controller, os.environ["EXECUTION_MANAGEMENT_TOKEN"]))
runner = OrderedDemoRun(controller)
app.include_router(create_demo_run_router(runner))


@app.middleware("http")
async def exclusive_demo(request, call_next):
    if (request.method == "POST" and request.url.path == "/api/runtime-model-offloading/generate"
            and runner.active):
        return JSONResponse({"detail": "demo_owns_request_generator"}, status_code=409)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/", include_in_schema=False)
async def page():
    return FileResponse(Path(__file__).parent / "static/ordered-demo/index.html")


@app.get("/demo.js", include_in_schema=False)
async def javascript():
    return FileResponse(Path(__file__).parent / "static/ordered-demo/demo.js", media_type="text/javascript")


@app.get("/demo.css", include_in_schema=False)
async def stylesheet():
    return FileResponse(Path(__file__).parent / "static/ordered-demo/demo.css", media_type="text/css")


@app.get("/health")
async def health():
    return {"running": controller.running, "state": controller.state,
            "scope": "isolated_ordered_model_demo"}
