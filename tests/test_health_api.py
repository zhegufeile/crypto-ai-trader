from fastapi.testclient import TestClient

from app.api.routes_health import router
from app.config import Settings
from fastapi import FastAPI


def test_health_ready_when_scheduler_disabled():
    app = FastAPI()
    app.include_router(router)
    app.state.scheduler = type("Scheduler", (), {"running": False})()

    from app.api import routes_health

    routes_health.get_settings.cache_clear()
    routes_health.get_settings = lambda: Settings(
        env="prod",
        use_simulation=False,
        scheduler_enabled=False,
        signal_strategy_tier_mode="core-only",
    )

    client = TestClient(app)
    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["scheduler_enabled"] is False
    assert payload["scheduler_running"] is False
