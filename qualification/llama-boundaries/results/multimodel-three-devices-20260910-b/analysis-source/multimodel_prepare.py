"""Pin and fetch the six Q8_0 checkpoints for the three-device experiment."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
import urllib.request

MODELS = ["llama3.2:1b-instruct-q8_0", "llama3.2:3b-instruct-q8_0",
          "qwen2.5:0.5b-instruct-q8_0", "qwen2.5:1.5b-instruct-q8_0",
          "qwen2.5:3b-instruct-q8_0", "gemma2:2b-instruct-q8_0"]


def prepare(model, root):
    name, tag = model.split(":")
    slug = model.replace(":", "-")
    url = f"https://registry.ollama.ai/v2/library/{name}/manifests/{tag}"
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read()
    manifest = json.loads(raw)
    layer, = [x for x in manifest["layers"] if x["mediaType"] == "application/vnd.ollama.image.model"]
    sha = layer["digest"].split(":")[1]
    target = root / (sha + ".gguf")
    local = Path.home() / ".ollama/models/blobs" / ("sha256-" + sha)
    if local.exists():
        target = local
    h = hashlib.sha256()
    started = time.monotonic()
    if target.exists():
        with target.open("rb") as f:
            for data in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(data)
    else:
        partial = target.with_suffix(".partial")
        blob_url = f"https://registry.ollama.ai/v2/library/{name}/blobs/{layer['digest']}"
        received = 0
        notified = time.monotonic()
        with urllib.request.urlopen(blob_url, timeout=60) as response, partial.open("xb") as f:
            while data := response.read(8 * 1024 * 1024):
                f.write(data)
                h.update(data)
                received += len(data)
                if time.monotonic() - notified > 20:
                    print(json.dumps({"model": model, "downloaded_bytes": received, "total_bytes": layer["size"]}), flush=True)
                    notified = time.monotonic()
                if time.monotonic() - started > 1800:
                    raise TimeoutError("model download deadline")
        if h.hexdigest() != sha or partial.stat().st_size != layer["size"]:
            raise ValueError("Downloaded model digest/size mismatch")
        partial.rename(target)
    if h.hexdigest() != sha or target.stat().st_size != layer["size"]:
        raise ValueError("Cached model digest/size mismatch")
    result = {"model": model, "slug": slug, "quantization": "Q8_0", "sha256": sha,
              "size_bytes": layer["size"], "path": str(target.resolve()), "source": url,
              "manifest_sha256": hashlib.sha256(raw).hexdigest(), "manifest": manifest,
              "upstream_revision": None, "verified_at": time.time()}
    (root / (slug + ".json")).write_text(json.dumps(result, indent=2))
    print(json.dumps({"model": model, "verified": True, "seconds": time.monotonic() - started}), flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(exist_ok=False, parents=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda m: prepare(m, a.output), MODELS))
    (a.output / "models.json").write_text(json.dumps(results, indent=2))
