from fastapi.testclient import TestClient

from sinew.main import app


def test_health_reaches_graph():
    body = TestClient(app).get("/api/health").json()
    assert body["ok"] is True
    assert body["nodes"] >= 0
