from fastapi.testclient import TestClient

from lira.api.main import app
from lira.version import __version__

client = TestClient(app)


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "name": "L.I.R.A. API",
        "version": __version__,
        "status": "online",
        "agentic": "true",
    }


def test_health_check_deps():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
