"""Resume incomplete device cells with device-owned processes and local logs.

KubeEdge exec connection lifetime is no longer the inference process lifetime.
Every server has a detached 900-second timeout, PID receipt and final cleanup.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import time
import bench
import multimodel_cluster as m
from multimodel_spark_cooled import COOLING


def read_remote(n, path):
    return m.command(m.prefix(n) + ["cat", path], 30)


def alive(n, pid):
    text = m.command(m.prefix(n) + ["sh", "-c", f"if [ -f /proc/{pid}/stat ]; then cat /proc/{pid}/stat; fi"])
    return bool(text and text.rsplit(")", 1)[1].split()[0] != "Z")


def cell(name, n, model, block, root):
    out = root / name / (model["slug"] + f"-b{block}")
    out.mkdir(parents=True, exist_ok=False)
    token = root.name + "-" + name + "-" + model["slug"] + f"-b{block}"
    assert re.fullmatch(r"[a-zA-Z0-9_.-]+", token)
    remote = "/dev/shm/" + token
    pidfile, exitfile, logfile = remote + ".pid", remote + ".exit", remote + ".log"
    cfg = m.runtime_config(n, model)
    r = cfg["runtime"]
    env = ["env", "LD_LIBRARY_PATH=" + r["library_path"], "GGML_BACKEND_PATH=" + r["backend_path"]]
    version = m.command(m.prefix(n) + env + [r["binary"], "--version"])
    assert "d222767c7" in version
    metrics = m.metrics(n)
    assert not metrics["active_requests"] and not metrics["queue_length"] and not metrics["model_vram_mib"]
    m.py(n, "import socket;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',18200));s.close()")
    m.command(m.prefix(n, "api") + ["mkdir", remote])
    for filename in ("bench.py", "multimodel_client.py"):
        m.command(m.K + ["-n", n["ns"], "cp", "--no-preserve=true", str(root / "source" / filename), n["pod"] + ":" + remote + "/" + filename, "-c", "api"])
    (out / "provenance.json").write_text(json.dumps({"node": name, "physical_node": n["node"], "pod_uid": n["uid"],
        "config": cfg, "model": model, "version": version, "block": block,
        "timing_scope": "device-local API sidecar to native loopback; detached processes; logs on tmpfs",
        "thermal_conditioning": "all observed host thermal zones <=60C before each case", "quality_evaluation": False}, indent=2))
    events, samples = bench.Journal(out / "events.jsonl"), bench.Journal(out / "resources.jsonl")
    pid, client_started, error = None, False, None
    cleanup = {"process_exited": False, "port_released": False}
    started = time.monotonic()
    try:
        inner = "echo $$ > " + shlex.quote(pidfile) + "; exec " + shlex.join(env + bench.runtime_args(cfg))
        wrapper = "timeout --signal=TERM --kill-after=15s 900 sh -c " + shlex.quote(inner) + " > " + shlex.quote(logfile) + " 2>&1; code=$?; echo $code > " + shlex.quote(exitfile)
        launch = "nohup setsid sh -c " + shlex.quote(wrapper) + " >/dev/null 2>&1 </dev/null &"
        m.command(m.prefix(n) + ["sh", "-c", launch])
        events.write({"event": "activation_started", "timestamp": time.time(), "detached_timeout_s": 900})
        m.py(n, "import time,urllib.request,json\nfor i in range(180):\n try:\n  if json.load(urllib.request.urlopen('http://127.0.0.1:18200/health',timeout=1)).get('status')=='ok':break\n except (OSError,ValueError):pass\n time.sleep(.5)\nelse:raise RuntimeError('activation deadline')", timeout=110)
        pid = read_remote(n, pidfile).strip()
        assert pid.isdigit()
        log = read_remote(n, logfile)
        (out / "server.log").write_text(log)
        layers = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", log)
        maps = read_remote(n, "/proc/" + pid + "/maps")
        assert layers and layers[-1][0] == layers[-1][1] and int(layers[-1][0]) > 0 and "libggml-cuda.so" in maps
        events.write({"event": "gpu_health_ready", "timestamp": time.time(), "layers": layers[-1], "pid": pid,
                      "activation_health_ms": (time.monotonic()-started)*1000})
        args = ["python", remote + "/multimodel_client.py", "--output", remote + "/workload", "--node", n["node"], "--block", str(block)]
        runner = "import subprocess,pathlib; p=subprocess.run(" + repr(args) + ");pathlib.Path(" + repr(remote+"/client.exit") + ").write_text(str(p.returncode))"
        m.py(n, "import subprocess,sys;f=open(sys.argv[1],'w');p=subprocess.Popen([sys.executable,'-c',sys.argv[2]],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);print(p.pid)", remote+"/client.log", runner)
        client_started = True
        print(json.dumps({"event": "detached_cell_started", "node": name, "model": model["model"], "block": block}), flush=True)
        while True:
            code = m.py(n, "from pathlib import Path;import sys;p=Path(sys.argv[1]);print(p.read_text() if p.exists() else 'running')", remote+"/client.exit").strip()
            if code != "running":
                if code != "0":
                    raise RuntimeError("Detached client failed: " + code)
                break
            if not alive(n, pid) or time.monotonic()-started > 840:
                raise RuntimeError("Native process or experiment deadline")
            shell = f"cat /proc/{pid}/status; cat /proc/meminfo; nvidia-smi --query-gpu=name,temperature.gpu,memory.used,power.draw --format=csv,noheader,nounits 2>/dev/null || true; cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null || true"
            sample = m.command(m.prefix(n) + ["sh", "-c", shell])
            samples.write({"timestamp": time.time(), "sample": sample})
            available = re.search(r"MemAvailable:\s+(\d+)", sample)
            temps = re.findall(r"(?m)^([0-9]{4,6})$", sample)
            if available and int(available[1]) < 700*1024 or any(int(t) >= 80000 for t in temps):
                raise RuntimeError("RAM or temperature guard")
            time.sleep(3)
    except Exception as exc:
        error = repr(exc)
    finally:
        try:
            if pid is None:
                pid = read_remote(n, pidfile).strip()
            assert pid.isdigit()
            if alive(n, pid):
                cmdline = read_remote(n, "/proc/"+pid+"/cmdline")
                assert cfg["model"]["path"] in cmdline and "18200" in cmdline
                m.command(m.prefix(n)+["kill","-TERM",pid])
                limit = time.monotonic()+25
                while alive(n,pid) and time.monotonic()<limit:
                    time.sleep(1)
                if alive(n,pid):
                    m.command(m.prefix(n)+["kill","-KILL",pid])
                    time.sleep(1)
            cleanup["process_exited"] = not alive(n,pid)
            m.py(n,"import socket;s=socket.socket();s.settimeout(2);assert s.connect_ex(('127.0.0.1',18200))!=0;s.close()")
            cleanup["port_released"] = True
        except Exception as exc:
            cleanup["error"] = repr(exc)
        if client_started:
            limit=time.monotonic()+190
            while time.monotonic()<limit:
                code=m.py(n,"from pathlib import Path;import sys;print(Path(sys.argv[1]).exists())",remote+"/client.exit").strip()
                if code=="True":break
                time.sleep(2)
        try:
            m.command(m.K+["-n",n["ns"],"cp",n["pod"]+":"+remote+"/workload",str(out/"workload"),"-c","api"],60)
            (out/"client.log").write_text(m.py(n,"from pathlib import Path;import sys;print(Path(sys.argv[1]).read_text())",remote+"/client.log"))
            m.command(m.K+["-n",n["ns"],"cp",n["pod"]+":"+logfile,str(out/"server.log"),"-c","inference-runtime"],90)
            expected=m.command(m.prefix(n)+["sha256sum",logfile]).split()[0]
            assert expected==bench.digest(out/"server.log")
            # Remove only our exported tmpfs runtime log; checkpoint caches retained.
            m.command(m.prefix(n)+["rm",logfile])
        except Exception as exc:
            cleanup["export_error"]=repr(exc)
        events.close(); samples.close()
        (out/"cleanup.json").write_text(json.dumps(cleanup,indent=2))
        (out/"outcome.json").write_text(json.dumps({"error":error,"at":time.time()},indent=2))
    if error or not cleanup["process_exited"] or not cleanup["port_released"] or cleanup.get("export_error"):
        raise RuntimeError(str(error or cleanup))
    print(json.dumps({"event":"detached_cell_complete","node":name,"model":model["model"],"block":block}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--parent",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--node",choices=list(m.NODES),required=True)
    a=p.parse_args(); root=a.output.resolve(); root.mkdir(exist_ok=False,parents=True)
    models=json.loads((a.parent/"models.json").read_text()); plan=json.loads((a.parent/"plan.json").read_text())
    nodes=m.pin_nodes(); n=nodes[a.node]; uid=json.loads((a.parent/"owner.json").read_text())["uid"]
    (root/"models.json").write_text(json.dumps(models,indent=2))
    (root/"nodes-before.json").write_text(json.dumps(nodes,indent=2))
    (root/"plan.json").write_text(json.dumps({**plan,"nodes":[a.node],"parent":str(a.parent),"thermal_conditioning":"<=60C before case","transport":"detached device-local runtime and client"},indent=2))
    source=root/"source";source.mkdir()
    client=(m.HERE/"multimodel_client.py").read_text()
    (source/"multimodel_client.py").write_text(client.replace("import bench\n","import bench\n"+COOLING))
    (source/"bench.py").write_text((m.HERE/"bench.py").read_text())
    (source/"multimodel_detached.py").write_text(Path(__file__).read_text())
    (root/"source-hashes.json").write_text(json.dumps({f.name:bench.digest(f) for f in source.iterdir()},indent=2))
    paused_here=False
    try:
        for block,slugs in enumerate(plan["order"]):
            for slug in slugs:
                old=a.parent/a.node/(slug+f"-b{block}")
                if (old/"workload/complete.json").exists() and json.loads((old/"cleanup.json").read_text()).get("port_released"):
                    continue
                current=m.service();assert current["metadata"]["uid"]==uid
                if not current["spec"]["suspended"]:
                    if current["status"].get("load",{}).get("inFlightAndPending",0):
                        raise RuntimeError("Original service has live requests")
                    m.set_suspended(False,True,uid);paused_here=True;m.wait_phase("Suspended")
                cell(a.node,n,next(x for x in models if x["slug"]==slug),block,root)
    finally:
        if paused_here:
            m.set_suspended(True,False,uid)
            (root/"service-restored.json").write_text(json.dumps(m.wait_phase("Serving",120),indent=2))
        (root/"nodes-after.json").write_text(json.dumps(m.pin_nodes(),indent=2))


if __name__=="__main__":main()
