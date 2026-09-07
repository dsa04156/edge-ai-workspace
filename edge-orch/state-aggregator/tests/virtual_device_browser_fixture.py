"""Local browser QA only: simulated Kubernetes placement + real local HTTP model.

No Kubernetes client is constructed. Run the model with POD_UID=local-qa-pod.
The fixture is not a cluster verification or production application.
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.virtual_resources import VirtualDeviceObserver
from app.virtual_resource_registry import VirtualDeviceRegistry

STATIC = Path(__file__).parents[1] / "app/static"
CONTROL = Path(os.getenv("VD_QA_STATE", "/tmp/vd-qa-state"))


class LocalReader:
    async def nodes(self):
        return [{"name":"LOCAL-QA-SIMULATED-SERVER","ready":True}]

    async def workload(self, definition):
        mode = CONTROL.read_text().strip() if CONTROL.exists() else "running"
        if mode == "error":
            raise RuntimeError("local QA simulated Kubernetes outage")
        pods = [] if mode == "stopped" else [{
            "podUid":"local-qa-pod", "name":"local-qa-pod", "namespace":"virtual-device-test",
            "node":"LOCAL-QA-SIMULATED-SERVER", "podIp":"127.0.0.1", "phase":"Running",
            "terminating":False, "podReady":True, "resources":[{"container":"inference",
                "requests":{"cpu":"100m","memory":"64Mi"},"limits":{"cpu":"1","memory":"256Mi"}}],
            "podReasons":[],
        }]
        return {"instances":pods, "desiredReplicas":len(pods), "workloadExists":True,
                "plannedNodeSelector":{"test":"LOCAL QA ONLY"}, "terminalPods":[]}


registry = VirtualDeviceRegistry.load()
registry.resources[0].spec.runtimeRef.port = int(os.getenv("VD_QA_RUNTIME_PORT", "18081"))
observer = VirtualDeviceObserver(LocalReader())
app = FastAPI(title="Local fixture — simulated placement, real CPU model")
app.mount("/static", StaticFiles(directory=STATIC))


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/virtual-devices")
async def virtual_devices():
    return await observer.snapshot(registry)


@app.get("/api/{path:path}")
async def other_api(path: str):
    return JSONResponse(status_code=503, content={"error":"other sources disabled in local QA fixture"})
