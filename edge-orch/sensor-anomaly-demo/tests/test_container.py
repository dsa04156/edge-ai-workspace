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
