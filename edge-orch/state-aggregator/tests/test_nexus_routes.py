"""Public entry points and embedded tools must resolve their complete asset graph."""
import re
from fastapi.testclient import TestClient
from app.main import app


def test_nexus_and_existing_tools_are_served_with_resolvable_assets():
    client = TestClient(app)
    for route, marker in [("/", "NEXUS"), ("/dashboard", "NEXUS"), ("/classic?workspace=1", "deviceManagementTitle")]:
        response = client.get(route)
        assert response.status_code == 200
        assert marker in response.text
        for asset in re.findall(r'(?:src|href)="(/static/[^\"]+)"', response.text):
            result = client.get(asset)
            assert result.status_code == 200, asset
            assert "text/html" not in result.headers.get("content-type", ""), asset
