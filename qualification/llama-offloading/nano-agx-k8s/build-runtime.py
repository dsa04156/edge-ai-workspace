"""Repack the pinned official ARM64 image, preserving the JetPack 6 backend bytes.

No Docker daemon, host libraries, compilation, or registry writes. Produces an OCI
archive for explicit offline containerd import and records both artifact identities.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time
import urllib.request

PARENT = "sha256:8818bcd5de52f6eb15376687a7367c7a1c69fc1a0115a4e326ae79261ec6fbab"
DROP = {"cuda_v12", "cuda_v13", "cuda_jetpack5"}
REPOSITORY = "localhost/qualification/ollama-jetson"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def keep(name):
    parts = name.lstrip("./").split("/")
    return not (len(parts) >= 4 and parts[:3] == ["usr", "lib", "ollama"] and parts[3] in DROP)


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    blobs = output / "blobs" / "sha256"
    blobs.mkdir(parents=True, exist_ok=True)
    token = json.load(urllib.request.urlopen(
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ollama/ollama:pull"))["token"]

    def fetch(kind, digest):
        path = blobs / digest.split(":")[1]
        if path.exists() and sha(path) == digest.split(":")[1]:
            return path
        request = urllib.request.Request(f"https://registry-1.docker.io/v2/ollama/ollama/{kind}/{digest}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.docker.distribution.manifest.v2+json"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as f:
                    while chunk := response.read(1024 * 1024):
                        f.write(chunk)
                break
            except OSError:
                if attempt == 4:
                    raise RuntimeError("upstream download failed after five attempts") from None
                print(f"download retry {attempt + 1}/4 for {digest}", flush=True)
                time.sleep(2)
        if sha(path) != digest.split(":")[1]:
            raise ValueError("upstream digest mismatch")
        return path

    def put(data):
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        (blobs / digest).write_bytes(encoded)
        return {"digest": "sha256:" + digest, "size": len(encoded)}

    manifest = json.loads(fetch("manifests", PARENT).read_bytes())
    config = json.loads(fetch("blobs", manifest["config"]["digest"]).read_bytes())
    if config["architecture"] != "arm64" or config["os"] != "linux":
        raise ValueError("unexpected platform")
    layers, diff_ids, records = [], [], []
    unpacked_bytes = 0
    for index, layer in enumerate(manifest["layers"]):
        print(f"fetch layer {index + 1}/{len(manifest['layers'])}: {layer['size']} bytes", flush=True)
        original = fetch("blobs", layer["digest"])
        # Inspect names first. Reuse untouched base layers byte-for-byte.
        with tarfile.open(original, "r:gz") as src:
            members = src.getmembers()
        unpacked_bytes += sum(m.size for m in members if m.isfile() and keep(m.name))
        removed = [m for m in members if not keep(m.name)]
        if not removed:
            layers.append(layer)
            diff_ids.append(config["rootfs"]["diff_ids"][index])
            continue
        raw = output / "trimmed.tar"
        with tarfile.open(original, "r:gz") as src, tarfile.open(raw, "w") as dst:
            for member in src:
                if keep(member.name):
                    dst.addfile(member, src.extractfile(member) if member.isfile() else None)
        diff_ids.append("sha256:" + sha(raw))
        compressed = output / "trimmed.tar.gz"
        with raw.open("rb") as src, compressed.open("wb") as target:
            with gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0, compresslevel=6) as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(chunk)
        digest = sha(compressed)
        compressed.replace(blobs / digest)
        layers.append({"mediaType": layer["mediaType"], "digest": "sha256:" + digest,
                       "size": (blobs / digest).stat().st_size})
        records.append({"layer": index, "removed_regular_bytes": sum(m.size for m in removed if m.isfile()),
                        "removed_paths": [m.name for m in removed], "retained_tar_bytes": raw.stat().st_size})
        raw.unlink()
    if not records or not any("cuda_jetpack6" in m.name for m in members):
        raise ValueError("expected Jetson backend layout missing")
    config["rootfs"]["diff_ids"] = diff_ids
    config["config"].setdefault("Labels", {})["org.opencontainers.image.base.digest"] = PARENT
    config["config"].setdefault("Env", []).append("JETSON_JETPACK=6")
    config_desc = {"mediaType": manifest["config"]["mediaType"], **put(config)}
    result = {"schemaVersion": 2, "mediaType": manifest["mediaType"], "config": config_desc, "layers": layers}
    descriptor = {"mediaType": result["mediaType"], **put(result), "platform": {"os": "linux", "architecture": "arm64"}}
    image = REPOSITORY + "@" + descriptor["digest"]
    descriptor["annotations"] = {"io.containerd.image.name": image, "org.opencontainers.image.ref.name": "0.33.2-jetpack6"}
    (output / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": [descriptor]}))
    (output / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
    needed = {d["digest"].split(":")[1] for d in [*layers, config_desc, descriptor]}
    archive = output / "runtime.oci.tar"
    with tarfile.open(archive, "w") as dst:
        for name in ["index.json", "oci-layout"]:
            dst.add(output / name, arcname=name)
        for digest in sorted(needed):
            dst.add(blobs / digest, arcname="blobs/sha256/" + digest)
    evidence = {"parent_arm64_manifest": PARENT, "image": image, "archive_sha256": sha(archive),
                "archive_bytes": archive.stat().st_size, "compressed_layer_bytes": sum(d["size"] for d in layers),
                "unpacked_regular_bytes_upper_bound": unpacked_bytes,
                "removed_backends": sorted(DROP), "changes": records,
                "retained_files": "byte-for-byte official image; no runtime recompilation"}
    (output / "runtime-provenance.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({k: v for k, v in evidence.items() if k != "changes"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output)
