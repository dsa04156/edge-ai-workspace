"""Live, bounded, open-loop offloading demonstration. No synthetic live data."""
from __future__ import annotations

from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request, parse
import csv
import io
import json
import math
import os
import sqlite3
import threading
import time
import uuid

PROMPT = "In one short sentence, explain why edge computing reduces latency."
DIGEST = "baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878"
NODES = {
    "nano": {"label": "Jetson Orin Nano", "physical": "etri-dev0001-jetorn", "url": os.getenv("NANO_URL", "http://192.168.0.3:18100"), "service_ms": 198.4, "capacity": 16},
    "agx": {"label": "RTX 5060 Ti", "physical": "etri-ser0001-cg0msb", "url": os.getenv("AGX_URL", "http://192.168.0.56:18100"), "service_ms": 190.4, "capacity": 4},
    "spark": {"label": "RTX 5080", "physical": "etri-ser0002-cgnmsb", "url": os.getenv("SPARK_URL", "http://192.168.0.5:18100"), "service_ms": 21.9, "capacity": 16},
}
METHODS = ("nano_only", "cached_on_demand", "always_on", "cold_on_demand")


def http(url, payload=None, timeout=4):
    body = None if payload is None else json.dumps(payload).encode()
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def percentile(values, fraction=.95):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * fraction
    low, high = math.floor(pos), math.ceil(pos)
    return round(values[low] + (values[high] - values[low]) * (pos - low), 3)


def schedule(stages):
    result, offset = [], 0.0
    for stage in stages:
        seconds, rate = stage["seconds"], stage["rps"]
        result.extend((offset + i / rate, stage["name"]) for i in range(int(seconds * rate)))
        offset += seconds
    return result


def choose_node(method, target, remote_ready, inflight, snapshots, nano_ms, remote_ms, now):
    """Filter readiness before scoring, so an unavailable preferred node cannot block peers."""
    candidates=[]
    for node in ("nano", target):
        if node != "nano" and (method == "nano_only" or not remote_ready):
            continue
        snapshot=snapshots.get(node,{})
        if (snapshot.get("inference_ready") and 0 <= now-snapshot.get("observed_at",0) <= 3
                and inflight.get(node,0) < NODES[node]["capacity"]):
            candidates.append(node)
    if "nano" in candidates and inflight.get("nano",0) < 2:
        return "nano"
    return min(candidates,key=lambda n:(inflight.get(n,0)+1)*(nano_ms if n=="nano" else remote_ms)) if candidates else None


def summarize(run):
    rows = run["requests"]
    ok = [r for r in rows if r["status"] == "ok"]
    remote = [r for r in ok if r["selected_node"] != "nano"]
    start = run.get("workload_started", run["started"])
    duration = max(.001, max([r.get("completed_timestamp", start) for r in rows] + [run.get("arrival_ended", start)]) - start)
    identity = all(r.get("identity_verified") for r in ok)
    ids = [r["request_id"] for r in rows]
    dispatched = [e for e in run["events"] if e["event"] == "dispatch"]
    return {
        "completed": len(ok), "errors": len(rows) - len(ok), "planned": run["planned"],
        "p95_latency_ms": percentile([r["latency_ms"] for r in ok]),
        "p95_ttft_ms": percentile([r["ttft_ms"] for r in ok]),
        "throughput_rps": round(len(ok) / duration, 3),
        "slo_violations": sum(r["ttft_ms"] > 1500 for r in ok),
        "by_node": dict(Counter(r["selected_node"] for r in ok)),
        "checks": {
            "all_requests_accounted": len(rows) == run["planned"],
            "no_request_errors": len(ok) == len(rows) and bool(rows),
            "unique_request_ids": len(ids) == len(set(ids)),
            "worker_identity_verified": identity and bool(ok),
            "ready_before_dispatch": bool(dispatched) and all(e["ready"] for e in dispatched),
            "forwarded_once": len(dispatched) == len(set(e["request_id"] for e in dispatched)),
            "remote_processing_observed": bool(remote) if run["method"] != "nano_only" else None,
            "idle_release_observed": any(e["event"] == "released" for e in run["events"]) if run["method"] in ("cached_on_demand", "cold_on_demand") and remote else None,
        },
    }


class Demo:
    def __init__(self, data_dir, transport=http, gpu=None):
        self.gpu = gpu
        self.transport = transport
        self.lock = threading.RLock()
        self.snapshots = {}
        self.runs = []
        self.busy = False
        self.stop = threading.Event()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.data_dir / "demo.sqlite"), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        for (body,) in self.db.execute("SELECT body FROM runs ORDER BY rowid DESC LIMIT 20"):
            run = json.loads(body)
            if run["status"] not in ("completed", "failed", "stopped", "interrupted"):
                run["status"] = "interrupted"
                run["error"] = "Controller restarted; no automatic replay. Check worker state before restarting."
            self.runs.append(run)
        self.runs.reverse()

    def call(self, node, path, payload=None, timeout=4):
        return self.transport(NODES[node]["url"] + path, payload, timeout)

    def save(self, run):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (run["id"], json.dumps(run)))
            self.db.commit()

    def event(self, run, event, **fields):
        with self.lock:
            run["events"].append({"timestamp": time.time(), "event": event, **fields})

    def poll_node(self, node):
        started = time.time()
        try:
            h = self.call(node, "/health", timeout=2)
            m = self.call(node, "/metrics", timeout=2)
            return {**m, **h, "available": bool(h.get("management_runtime_running")), "observed_at": time.time(), "poll_ms": round((time.time()-started)*1000, 1)}
        except Exception as exc:
            return {"available": False, "node_state": "UNKNOWN", "inference_ready": False, "observed_at": time.time(), "error": str(exc)}

    def poll(self):
        def observe(node):
            while True:
                snapshot=self.poll_node(node)
                with self.lock:
                    self.snapshots[node]=snapshot
                time.sleep(.5)
        # Each node has its own cadence; a timeout cannot age healthy peers' snapshots.
        threads=[threading.Thread(target=observe,args=(node,),daemon=True) for node in NODES]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def view(self):
        with self.lock:
            runs = [{**{k:v for k,v in r.items() if k not in ("requests", "samples", "events")},
                     "summary": summarize(r), "events": [e for e in r["events"] if e["event"]!="dispatch"], "samples": r["samples"][-360:],
                     "requests": r["requests"][-30:]} for r in self.runs[-8:]]
            return json.loads(json.dumps({"timestamp": time.time(), "busy": self.busy, "nodes": {
                k: {"label": n["label"], "physical": n["physical"], **self.snapshots.get(k, {})} for k,n in NODES.items()},
                "runs": runs, "policy": {"queue_high":8,"dwell_seconds":2,"min_gain":.15,"idle_seconds":30},
                "measurement": "live_worker_api", "model_digest": DIGEST,
                "gpu_automation": self.gpu is not None,
                "gpu_session": self.gpu.view() if self.gpu else None}))

    def start(self, payload):
        method = payload.get("method", "cached_on_demand")
        if method not in (*METHODS, "compare"):
            raise ValueError("Unknown method")
        target = payload.get("target", "spark")
        if target not in ("agx", "spark"):
            raise ValueError("Unknown target")
        if self.gpu and target != 'spark':
            raise ValueError('자동 GPU 시연은 승인된 RTX 5080만 지원합니다')
        # Fixed open-loop workload; callers cannot provide commands or node URLs.
        stages = [{"name":"평시","seconds":10,"rps":1}, {"name":"부하 집중","seconds":20,"rps":12}, {"name":"부하 감소","seconds":10,"rps":2}]
        with self.lock:
            if self.busy:
                raise RuntimeError("A run is already active")
            if self.gpu and self.gpu.active():
                raise RuntimeError('GPU 복원 중입니다. 복원 완료 후 다시 시작하세요')
            self.busy = True
            self.stop.clear()
        thread = threading.Thread(target=self.execute, args=(method,target,stages), daemon=True)
        thread.start()
        return {"accepted":True}

    def execute(self, method, target, stages):
        group = uuid.uuid4().hex[:12]
        try:
            if self.gpu:
                h = self.call('nano', '/health')
                m = self.call('nano', '/metrics')
                if h.get('node_id') != NODES['nano']['physical'] or not h.get('management_runtime_running') or m.get('active_requests') or m.get('queue_length'):
                    raise RuntimeError('Nano 준비/유휴 조건 확인 실패')
                self.gpu.acquire(self.stop)
                if self.stop.is_set():
                    return
            for selected in (("nano_only", "cached_on_demand") if method == "compare" else (method,)):
                run = self.run(selected, target, stages, group)
                if self.stop.is_set() or run["status"] != "completed":
                    break
        except Exception as exc:
            # Also persist preflight failures that happened before any workload exists.
            run = {'id':uuid.uuid4().hex[:12], 'group':group, 'method':method, 'target':target,
                   'status':'stopped' if self.stop.is_set() else 'failed', 'started':time.time(), 'finished':time.time(),
                   'planned':0, 'requests':[], 'events':[], 'samples':[], 'error':str(exc)}
            with self.lock:
                self.runs.append(run)
            self.save(run)
        finally:
            if self.gpu:
                self.recover_gpu()
                for run in self.runs:
                    if run.get('group') == group:
                        run['gpu_session'] = self.gpu.view()
                        self.save(run)
            with self.lock:
                self.busy = False

    def recover_gpu(self):
        # No inference is replayed. An unavailable API stays visibly blocked and retries.
        while self.gpu and self.gpu.active():
            try:
                self.gpu.restore()
            except Exception:
                time.sleep(5)

    def recover_on_startup(self):
        if self.gpu and self.gpu.active():
            self.busy = True
            self.recover_gpu()
            for run in self.runs:
                if run.get('gpu_session_id') == self.gpu.view()['id']:
                    run['gpu_session'] = self.gpu.view()
                    self.save(run)
            self.busy = False

    def run(self, method, target, stages, group):
        arrivals = schedule(stages)
        run = {"id":uuid.uuid4().hex[:12],"group":group,"method":method,"target":target,
               "status":"preparing","started":time.time(),"stages":stages,"planned":len(arrivals),
               "prompt":PROMPT,"max_tokens":8,"requests":[],"events":[],"samples":[]}
        if self.gpu:
            run['gpu_session_id'] = self.gpu.view()['id']
        with self.lock:
            self.runs.append(run)
        self.save(run)
        activated = threading.Event()
        activation_thread = None
        activation_failed = False
        inflight = Counter()
        pending = deque()
        submitted = []
        last_remote = time.monotonic()
        owns_target = False
        try:
            for node in ("nano", target):
                h = self.call(node, "/health")
                if not h.get("management_runtime_running") or h.get("node_id") != NODES[node]["physical"]:
                    raise RuntimeError(f"{node}: runtime unavailable or physical node mismatch")
                m = self.call(node, "/metrics")
                if m.get("active_requests",0) or m.get("queue_length",0):
                    raise RuntimeError(f"{node}: another workload is already using the worker")
            self.event(run,"setup_started")
            owns_target = True
            self.call("nano", "/activate", {"target_state":"ACTIVE", "reason":"demo_setup"}, 180)
            if method == "always_on":
                self.call(target, "/activate", {"target_state":"ACTIVE","reason":"demo_always_on"}, 180)
            elif method == "cached_on_demand":
                self.call(target, "/activate", {"target_state":"CACHED","reason":"demo_cache_prime"}, 180)
            else:
                self.call(target, "/deactivate", {"target_state":"COLD" if method=="cold_on_demand" else "CACHED", "reason":"demo_setup"}, 180)
            for node in ("nano", target):
                h = self.call(node, "/health")
                if h.get("model_cached") and h.get("model_digest") != DIGEST:
                    raise RuntimeError(f"{node}: model digest mismatch")
            run["status"] = "running"
            run["workload_started"] = time.time()
            base = time.monotonic()
            self.event(run,"workload_started", planned=len(arrivals))
            index, pressure_since, next_sample = 0, None, 0.0
            remote_ready = method == "always_on"
            self.save(run)

            def activate():
                nonlocal activation_failed
                try:
                    self.event(run,"activation_started", node=target)
                    a = self.call(target,"/activate", {"target_state":"ACTIVE","reason":"demo_sustained_pressure_gain"},180)
                    h = self.call(target,"/health")
                    if not h.get("inference_ready") or h.get("model_digest") != DIGEST:
                        raise RuntimeError("Remote did not become READY with the expected model")
                    self.event(run,"ready",node=target,activation_ms=a.get("activation_time_ms"))
                    activated.set()
                except Exception as exc:
                    activation_failed = True
                    self.event(run,"activation_failed",node=target,error=str(exc))

            def send(row, node):
                nonlocal last_remote
                try:
                    answer = self.call(node,"/generate", {"request_id":row["request_id"],"prompt":PROMPT,"max_tokens":8},120)
                    verified = answer.get("request_id")==row["request_id"] and answer.get("node_id")==NODES[node]["physical"] and answer.get("model_digest")==DIGEST
                    if not verified:
                        raise RuntimeError("Worker response request/node/model identity mismatch")
                    row.update(status="ok",identity_verified=True,actual_node=answer["node_id"],model_digest=answer["model_digest"],
                               ttft_ms=answer["ttft_ms"]+(row["dispatched_timestamp"]-row["timestamp"])*1000,
                               tokens_per_second=answer["tokens_per_second"],response=answer["response"])
                except Exception as exc:
                    row.update(status="error",error=str(exc),identity_verified=False)
                finally:
                    row.update(completed_timestamp=time.time(),latency_ms=(time.time()-row["timestamp"])*1000)
                    with self.lock:
                        inflight[node]-=1
                        run["requests"].append(row)
                        if node == target:
                            last_remote = time.monotonic()
                            if row["status"] == "ok" and not run.get("first_remote_request_id"):
                                run["first_remote_request_id"]=row["request_id"]
                                self.event(run,"first_remote_response",node=node,request_id=row["request_id"],actual_node=row["actual_node"],model_digest=row["model_digest"])

            with ThreadPoolExecutor(max_workers=32) as pool:
                while index<len(arrivals) or pending or sum(inflight.values()):
                    now = time.monotonic()
                    elapsed = now-base
                    if self.stop.is_set():
                        while index<len(arrivals):
                            due, phase = arrivals[index]
                            run["requests"].append({"request_id":f'{run["id"]}-{index}',"status":"cancelled","timestamp":run["workload_started"]+due,"completed_timestamp":time.time(),"error":"stopped before arrival"})
                            index+=1
                        while pending:
                            row=pending.popleft()
                            row.update(status="cancelled",completed_timestamp=time.time(),error="stopped before dispatch")
                            run["requests"].append(row)
                    while index<len(arrivals) and elapsed>=arrivals[index][0]:
                        due,phase=arrivals[index]
                        pending.append({"request_id":f'{run["id"]}-{index}',"timestamp":run["workload_started"]+due,"scheduled_offset":due,"phase":phase})
                        index+=1
                    if index==len(arrivals) and "arrival_ended" not in run:
                        run["arrival_ended"]=time.time()
                    with self.lock:
                        snaps = dict(self.snapshots)
                        ahead = inflight["nano"] + len(pending)
                    nm=snaps.get("nano",{})
                    tps=float(nm.get("ewma_tokens_per_second") or 0)
                    pressure = bool(pending) and (ahead>=8 or float(nm.get("ewma_ttft_ms") or 0)>=1500 or 0<tps<=39.5)
                    pressure_since = (pressure_since or now) if pressure else None
                    nano_service = max(1,float(snaps.get("nano",{}).get("ewma_inference_ms") or NODES["nano"]["service_ms"]))
                    remote_service = max(1,float(snaps.get(target,{}).get("ewma_inference_ms") or NODES[target]["service_ms"]))
                    activation_cost = {"cached_on_demand":1847 if target=="spark" else 2329,"cold_on_demand":26980 if target=="spark" else 19074}.get(method,0)
                    nano_cost = (ahead+1)*nano_service
                    remote_cost = activation_cost+remote_service+2
                    gain = 1-remote_cost/nano_cost
                    if method not in ("nano_only","always_on") and not activation_thread and not self.stop.is_set() and pressure_since and now-pressure_since>=2 and gain>=.15:
                        self.event(run,"pressure_detected",node="nano",queue=ahead,gain=round(gain,3),nano_cost_ms=nano_cost,remote_cost_ms=remote_cost)
                        activation_thread=threading.Thread(target=activate,daemon=True)
                        activation_thread.start()
                    if activated.is_set():
                        remote_ready=True
                    while pending and not self.stop.is_set():
                        with self.lock:
                            node=choose_node(method,target,remote_ready,inflight,snaps,nano_service,remote_service,time.time())
                        if node is None:
                            break
                        h=snaps.get(node,{})
                        row=pending.popleft()
                        if (node == 'nano' and row.get('phase') == '부하 감소' and ahead < 2
                                and run.get('first_remote_request_id') and not run.get('nano_returned')):
                            run['nano_returned'] = True
                            self.event(run, 'nano_returned', node='nano', request_id=row['request_id'])
                        row.update(selected_node=node,dispatched_timestamp=time.time(),ready_observed_at=h["observed_at"])
                        self.event(run,"dispatch",node=node,request_id=row["request_id"],ready=True)
                        with self.lock:
                            inflight[node]+=1
                        submitted.append(pool.submit(send,row,node))
                    if elapsed>=next_sample:
                        with self.lock:
                            run["samples"].append({"timestamp":time.time(),"elapsed":elapsed,"queue":len(pending),"nano_outstanding":inflight["nano"],"remote_outstanding":inflight[target],"arrived":index,"nodes":snaps})
                        next_sample=elapsed+.5
                        self.save(run)
                    if elapsed>240:
                        raise TimeoutError("Workload deadline exceeded; inspect worker reachability")
                    time.sleep(.025)
            if activation_thread:
                activation_thread.join(timeout=185)
                if activation_thread.is_alive():
                    raise RuntimeError("Activation still in flight; cleanup requires inspection")
            run["status"]="releasing"
            self.event(run,"drained")
            # The last completed request is the idle anchor, not its arrival.
            if remote_ready and method in ("cached_on_demand","cold_on_demand"):
                while time.monotonic()-last_remote<30 and not self.stop.is_set():
                    run["idle_remaining"]=round(max(0,30-(time.monotonic()-last_remote)),1)
                    time.sleep(.5)
                h=self.call(target,"/metrics")
                if h.get("active_requests",0) or h.get("queue_length",0):
                    raise RuntimeError("Remote still busy at release")
                destination="COLD" if method=="cold_on_demand" else "CACHED"
                self.call(target,"/deactivate",{"target_state":destination,"reason":"demo_idle_30s"},180)
                h=self.call(target,"/health")
                if h.get("model_loaded") or h.get("node_state")!=destination:
                    raise RuntimeError("Remote model release not verified")
                self.event(run,"released",node=target,state=destination,observation=self.poll_node(target))
            run["status"]="stopped" if self.stop.is_set() else "completed"
            if activation_failed:
                run["warning"]="Remote activation failed; new requests continued on Nano."
        except Exception as exc:
            run["status"]="failed"
            run["error"]=str(exc)
            self.event(run,"failed",error=str(exc))
        finally:
            # Wait for any activation before cleanup; never unload in-flight requests.
            if activation_thread and activation_thread.is_alive():
                activation_thread.join(timeout=185)
            try:
                m=self.call(target,"/metrics") if owns_target else {}
                if owns_target and not m.get("active_requests",0) and not m.get("queue_length",0):
                    self.call(target,"/deactivate",{"target_state":"COLD" if method=="cold_on_demand" else "CACHED","reason":"demo_cleanup"},180)
                    self.event(run,"cleanup",node=target)
            except Exception as exc:
                run["cleanup_error"]=str(exc)
            run["finished"]=time.time()
            self.save(run)
        return run


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value, status=200, content_type="application/json; charset=utf-8"):
        body=json.dumps(value,ensure_ascii=False).encode() if not isinstance(value,bytes) else value
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path=parse.urlsplit(self.path).path
        if path=="/api/state":
            self.reply(self.server.demo.view())
        elif path=="/health":
            self.reply({"ok":True})
        elif path.startswith("/api/runs/"):
            runid=path.removeprefix("/api/runs/").removesuffix(".csv")
            with self.server.demo.lock:
                run=next((r for r in self.server.demo.runs if r["id"]==runid),None)
                run=json.loads(json.dumps(run))
            if not run:
                self.reply({"error":"not_found"},404)
            elif path.endswith(".csv"):
                buf=io.StringIO()
                fields=sorted({k for r in run["requests"] for k in r})
                writer=csv.DictWriter(buf,fieldnames=fields)
                writer.writeheader(); writer.writerows(run["requests"])
                self.reply(buf.getvalue().encode(),content_type="text/csv; charset=utf-8")
            else:
                self.reply({**run,"summary":summarize(run)})
        elif path in ("/","/app.js","/replay.js","/style.css"):
            name={"/":"index.html","/app.js":"app.js","/replay.js":"replay.js","/style.css":"style.css"}[path]
            types={"index.html":"text/html; charset=utf-8","app.js":"text/javascript; charset=utf-8","replay.js":"text/javascript; charset=utf-8","style.css":"text/css; charset=utf-8"}
            self.reply((Path(__file__).parent/"demo-web"/name).read_bytes(),content_type=types[name])
        else:
            self.reply({"error":"not_found"},404)

    def do_POST(self):
        # Same-origin browser control only; URLs/commands cannot be supplied by clients.
        if self.headers.get("Origin") and parse.urlsplit(self.headers["Origin"]).netloc != self.headers.get("Host"):
            return self.reply({"error":"cross_origin_denied"},403)
        if self.headers.get("X-Demo-Control")!="1":
            return self.reply({"error":"control_header_required"},403)
        try:
            length=int(self.headers.get("Content-Length",0))
            if length>4096:
                raise ValueError("Payload too large")
            payload=json.loads(self.rfile.read(length) or b"{}")
            if self.path=="/api/start":
                self.reply(self.server.demo.start(payload),202)
            elif self.path=="/api/stop":
                self.server.demo.stop.set()
                self.reply({"stopping":True})
            else:
                self.reply({"error":"not_found"},404)
        except (ValueError,RuntimeError) as exc:
            self.reply({"error":str(exc)},409)


if __name__=="__main__":
    data_dir = os.getenv('DEMO_DATA_DIR', '/data/demo')
    gpu = None
    if os.getenv('DEMO_GPU_AUTOMATION') == '1':
        from gpu_session import GPUSession
        gpu = GPUSession(data_dir)
    demo=Demo(data_dir, gpu=gpu)
    threading.Thread(target=demo.recover_on_startup,daemon=True).start()
    threading.Thread(target=demo.poll,daemon=True).start()
    server=ThreadingHTTPServer((os.getenv("HOST","0.0.0.0"),int(os.getenv("PORT","18102"))),Handler)
    server.request_queue_size=128
    server.demo=demo
    server.serve_forever()
