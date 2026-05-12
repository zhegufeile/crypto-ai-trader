import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    checks["database_url_present"] = bool(settings.database_url)
    checks["simulation_enabled"] = bool(settings.use_simulation)
    checks["frontend_origins_configured"] = bool(settings.frontend_origins)
    checks["onchain_signal_snapshot_exists"] = _optional_exists(settings.onchain_signal_snapshot_file)
    checks["onchain_risk_snapshot_exists"] = _optional_exists(settings.onchain_risk_snapshot_file)

    if settings.env != "prod":
        warnings.append("ENV is not prod")
    if not settings.use_simulation:
        warnings.append("USE_SIMULATION is false; verify live execution protections before deployment")
    if settings.signal_strategy_tier_mode not in {"core-only", "core+candidate", "all"}:
        warnings.append("SIGNAL_STRATEGY_TIER_MODE is not one of core-only/core+candidate/all")
    if settings.enable_onchain_signal_boost and settings.onchain_signal_snapshot_file and not checks["onchain_signal_snapshot_exists"]:
        warnings.append("configured ONCHAIN_SIGNAL_SNAPSHOT_FILE is missing")
    if settings.onchain_risk_snapshot_file and not checks["onchain_risk_snapshot_exists"]:
        warnings.append("configured ONCHAIN_RISK_SNAPSHOT_FILE is missing")

    result = {
        "status": "pass" if not warnings else "review",
        "env": settings.env,
        "signal_strategy_tier_mode": settings.signal_strategy_tier_mode,
        "checks": checks,
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


def _optional_exists(path_value: str | None) -> bool:
    if not path_value:
        return False
    return Path(path_value).exists()


if __name__ == "__main__":
    main()
