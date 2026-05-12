from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_root_serves_index():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Strategy Cards + Candidate Diagnostics" in response.text
    assert "Position Panel" in response.text
    assert "Avg TP1 Hit Rate" in response.text
    assert "Strategy Leaderboard" in response.text
    assert "Core + Candidate" in response.text
    assert "Core Only" in response.text
    assert "Journal Timeline" in response.text
