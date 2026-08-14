import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_runs_non_root_fastapi_on_port_8080() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.11-slim\n")
    assert "USER 65532:65532" in dockerfile
    assert "EXPOSE 8080" in dockerfile
    assert (
        'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]'
        in dockerfile
    )


def test_platform_builders_pin_distinct_base_manifests() -> None:
    arm64_script = (ROOT / "scripts" / "build-edge-arm64-oci.sh").read_text(
        encoding="utf-8"
    )
    amd64_script = (ROOT / "scripts" / "build-server1-oci.sh").read_text(
        encoding="utf-8"
    )

    arm64_base = re.search(r"^base_image=(.+)$", arm64_script, re.MULTILINE)
    amd64_base = re.search(r"^base_image=(.+)$", amd64_script, re.MULTILINE)

    assert arm64_base is not None
    assert amd64_base is not None
    assert arm64_base.group(1) != amd64_base.group(1)
    assert "--platform linux/arm64" in arm64_script
    assert "--platform linux/amd64" in amd64_script


def test_server1_image_includes_cuda_runtime_and_nvrtc() -> None:
    requirements = (ROOT / "requirements-server1.txt").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build-server1-oci.sh").read_text(
        encoding="utf-8"
    )

    assert "cupy-cuda12x==13.6.0" in requirements
    assert "nvidia-cuda-runtime-cu12==12.8.90" in requirements
    assert "nvidia-cuda-nvrtc-cu12==12.8.93" in requirements
    assert "--env CUPY_CACHE_DIR=/tmp/cupy-cache" in build_script
    assert "--env LD_LIBRARY_PATH=" in build_script
    assert "site-packages/nvidia/cuda_nvrtc/lib" in build_script
    assert "site-packages/nvidia/cuda_runtime/lib" in build_script
