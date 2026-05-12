from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_root_serves_index():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Control Center" in response.text
    assert "Overview" in response.text
    assert "Open Trades and PnL" in response.text
    assert "Strategy Cards" in response.text
    assert "Candidate Diagnostics" in response.text
    assert "Core + Candidate" in response.text
    assert "Core Only" in response.text
    assert "Trade Journal" in response.text
