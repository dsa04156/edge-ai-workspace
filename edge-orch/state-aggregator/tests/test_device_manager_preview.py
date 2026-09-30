import re
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.device_manager_preview import create_app


def preview(tmp_path, handler=None):
    settings = SimpleNamespace(device_manager_enabled=True, data_dir=tmp_path,
                               device_manager_read_base_url="http://read-source")
    return TestClient(create_app(settings, sources=object(),
                      read_transport=httpx.MockTransport(handler or (lambda r: httpx.Response(200, json={})))))


def test_existing_nexus_shell_includes_device_manager(tmp_path):
    client = preview(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="nav"' in response.text
    assert 'iframe' not in response.text
    assets = re.findall(r'(?:src|href)="(/static/[^\"]+)"', response.text)
    assert any(path.split("?")[0] == "/static/nexus/device-manager.js" for path in assets)
    assert any("platform.js" in path for path in assets)
    for path in assets:
        assert client.get(path).status_code == 200, path
    assert client.get("/dashboard").status_code == 200
    methods = {(r.path, method) for r in client.app.routes for method in getattr(r, "methods", [])}
    assert ("/api/v1/device-manager/nodes/{name}/profile-document", "PUT") in methods


def test_dashboard_bridge_only_forwards_reads_to_fixed_origin(tmp_path):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"nodes": []})
    client = preview(tmp_path, handle)
    assert client.get("/state/nodes?limit=12", headers={"Authorization": "not-forwarded"}).json() == {"nodes": []}
    assert str(requests[0].url) == "http://read-source/state/nodes?limit=12"
    assert "authorization" not in requests[0].headers
    for method in ["post", "put", "delete", "patch"]:
        assert getattr(client, method)("/api/runtime-services/example/start").status_code == 405
    assert len(requests) == 1
    assert client.get("/api/v1/device-manager/unknown").status_code == 404
    assert len(requests) == 1


def test_preview_requires_explicit_existing_read_source(tmp_path):
    settings = SimpleNamespace(device_manager_read_base_url="", data_dir=tmp_path)
    with pytest.raises(ValueError, match="DEVICE_MANAGER_READ_BASE_URL"):
        create_app(settings)
