"""Local browser fixture. Never reads or writes a cluster or real preview DB."""
import os
import time
import httpx
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


from app.common_runtime import RuntimeState
from app.device_manager_preview import create_app
from app.models import DeviceState, NodeSchedulingResource, NodeResourceUtilization, SchedulingResourceAmounts


class Sources:
    async def nodes(self):
        return [{"name":name,"uid":uid,"ready":True,"architecture":arch,"nodeType":"edge_ai_device",
                 "observedAt":datetime.now(timezone.utc).isoformat(),"capacity":{"cpu":"8","memory":"8Gi"}}
                for name,uid,arch in [("fixture-arm64","fixture-uid-arm","arm64"),("fixture-amd64","fixture-uid-amd","amd64")]]

    async def resources(self):
        amount=SchedulingResourceAmounts(cpu_cores=4,memory_bytes=4*1024**3)
        return [NodeSchedulingResource(node=n["name"],cpu_available=4,memoryAvailableGB=4,kubernetes_ready=True,
            architecture=n["architecture"],health="healthy",schedulable=True,allocatable=amount,available=amount,
            requested=SchedulingResourceAmounts(cpu_cores=0,memory_bytes=0),
            utilization=NodeResourceUtilization(cpu_ratio=.25,memory_ratio=.5,observed_at=datetime.now(timezone.utc)))
            for n in await self.nodes()]

    async def sensors(self):
        return [DeviceState(name="fixture-temperature",profile_name="fixture-edgex-profile",device_service_name="fixture-serial",
            physical_device_id="fixture-source",admin_state="UNLOCKED",operating_state="UP",connection_state="connected",
            telemetry_freshness="fresh",latest_event_timestamp=datetime.now(timezone.utc))]

    async def runtime(self):
        now=time.time()
        return RuntimeState.model_validate({"observed_at":now,"snapshot_age_seconds":0,"services":[{
            "name":"fixture-model","uid":"fixture-service-uid","phase":"Running","checkedAt":now,"serving":True,
            "active":{"name":"fixture-worker","node":"fixture-arm64","role":"edge","variant":"cpu","capacity":1}}]})


settings=SimpleNamespace(device_manager_enabled=True,device_manager_read_base_url="http://fixture-read-source",
                         data_dir=Path(os.environ["DEVICE_MANAGER_FIXTURE_DIR"]))
app=create_app(settings,sources=Sources(),read_transport=httpx.MockTransport(
    lambda request: httpx.Response(503,json={"detail":"Dashboard reads are outside this device fixture"})))
