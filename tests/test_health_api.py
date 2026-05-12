from fastapi.testclient import TestClient

from app.main import app


def test_health_api_returns_runtime_mode():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "signal_strategy_tier_mode" in payload


def test_health_ready_api_returns_readiness_payload():
    client = TestClient(app)
    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ready", "degraded"}
    assert "warnings" in payload
