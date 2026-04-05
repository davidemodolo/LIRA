from fastapi.testclient import TestClient

from lira.api.main import app
from lira.version import __version__

client = TestClient(app)


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "L.I.R.A. API"
    assert data["version"] == __version__
    assert data["status"] == "online"
    assert data["agentic"] == "true"
    assert data["dashboard"] == "/dashboard"


def test_health_check_deps():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
