from pathlib import Path

from fastapi import APIRouter, Request

from app.config import get_settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health(request: Request) -> dict:
    settings = get_settings()
    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "status": "ok",
        "env": settings.env,
        "simulation": settings.use_simulation,
        "market_data_source": settings.market_data_source,
        "signal_strategy_tier_mode": settings.signal_strategy_tier_mode,
        "scheduler_running": bool(getattr(scheduler, "running", False)),
        "scan_interval_seconds": settings.scan_interval_seconds,
    }


@router.get("/ready")
def readiness(request: Request) -> dict:
    settings = get_settings()
    scheduler = getattr(request.app.state, "scheduler", None)
    warnings: list[str] = []

    signal_snapshot_exists = _optional_file_exists(settings.onchain_signal_snapshot_file)
    risk_snapshot_exists = _optional_file_exists(settings.onchain_risk_snapshot_file)

    if settings.env != "prod":
        warnings.append("environment is not set to prod")
    if not settings.use_simulation:
        warnings.append("simulation mode is disabled; verify real execution safeguards before go-live")
    if settings.enable_onchain_signal_boost and not signal_snapshot_exists and settings.onchain_signal_snapshot_file:
        warnings.append("onchain signal snapshot file is configured but missing")
    if settings.onchain_risk_snapshot_file and not risk_snapshot_exists:
        warnings.append("onchain risk snapshot file is configured but missing")
    if settings.frontend_origins == [] and settings.env == "prod":
        warnings.append("frontend_origins is empty in prod")

    ready = bool(getattr(scheduler, "running", False))
    return {
        "status": "ready" if ready else "degraded",
        "scheduler_running": ready,
        "database_url": settings.database_url,
        "signal_strategy_tier_mode": settings.signal_strategy_tier_mode,
        "onchain_signal_snapshot_configured": bool(settings.onchain_signal_snapshot_file),
        "onchain_signal_snapshot_exists": signal_snapshot_exists,
        "onchain_risk_snapshot_configured": bool(settings.onchain_risk_snapshot_file),
        "onchain_risk_snapshot_exists": risk_snapshot_exists,
        "warnings": warnings,
    }


def _optional_file_exists(path_value: str | None) -> bool:
    if not path_value:
        return False
    return Path(path_value).exists()
