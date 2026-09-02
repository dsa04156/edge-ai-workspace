import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def render_docs_site():
    result = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "docs-site")],
        check=True,
        capture_output=True,
        text=True,
    )
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def test_amd64_docs_image_is_scheduled_only_on_amd64_nodes():
    deployment = next(
        document
        for document in render_docs_site()
        if document["kind"] == "Deployment"
        and document["metadata"]["name"] == "docs-html"
    )

    assert deployment["spec"]["template"]["spec"]["nodeSelector"] == {
        "kubernetes.io/arch": "amd64"
    }
