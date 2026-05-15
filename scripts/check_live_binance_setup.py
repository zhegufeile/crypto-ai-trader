import json

import httpx

from app.config import get_settings
from app.core.live_trader import BinanceLiveTrader


def main() -> None:
    settings = get_settings()
    trader = BinanceLiveTrader(settings=settings)

    result: dict[str, object] = {
        "env": settings.env,
        "use_simulation": settings.use_simulation,
        "live_trading_enabled": settings.live_trading_enabled,
        "binance_testnet": settings.binance_testnet,
        "binance_margin_type": settings.binance_margin_type,
        "binance_futures_leverage": settings.binance_futures_leverage,
        "live_max_total_notional_usdt": settings.live_max_total_notional_usdt,
        "max_position_notional_usdt": settings.max_position_notional_usdt,
        "checks": [],
    }

    def add_check(name: str, ok: bool, details: dict[str, object] | None = None) -> None:
        result["checks"].append(
            {
                "name": name,
                "ok": ok,
                "details": details or {},
            }
        )

    add_check(
        "config_flags",
        ok=(settings.use_simulation is False and settings.live_trading_enabled is True),
        details={
            "use_simulation": settings.use_simulation,
            "live_trading_enabled": settings.live_trading_enabled,
        },
    )

    add_check(
        "credentials_present",
        ok=bool(settings.binance_api_key and settings.binance_api_secret),
        details={
            "api_key_present": bool(settings.binance_api_key),
            "api_secret_present": bool(settings.binance_api_secret),
        },
    )

    try:
        server_time = trader._public_request("GET", "/fapi/v1/time", {})
        add_check("public_time", ok=True, details={"server_time": server_time.get("serverTime")})
    except Exception as exc:
        add_check("public_time", ok=False, details={"error": str(exc)})

    try:
        account = trader._signed_request("GET", "/fapi/v2/account", {})
        positions = account.get("positions", [])
        active_positions = [item for item in positions if abs(float(item.get("positionAmt", 0) or 0)) > 0]
        add_check(
            "signed_account_access",
            ok=True,
            details={
                "available_balance": account.get("availableBalance"),
                "total_wallet_balance": account.get("totalWalletBalance"),
                "active_positions": len(active_positions),
                "fee_tier": account.get("feeTier"),
                "can_trade": account.get("canTrade"),
            },
        )
    except Exception as exc:
        add_check("signed_account_access", ok=False, details={"error": str(exc)})

    try:
        exchange_info = trader._public_request("GET", "/fapi/v1/exchangeInfo", {})
        add_check(
            "exchange_info_access",
            ok=True,
            details={"symbols_count": len(exchange_info.get("symbols", []))},
        )
    except Exception as exc:
        add_check("exchange_info_access", ok=False, details={"error": str(exc)})

    if settings.live_whitelisted_symbols:
        symbol_checks = []
        for symbol in settings.live_whitelisted_symbols:
            try:
                rules = trader._get_symbol_rules(symbol)
                symbol_checks.append(
                    {
                        "symbol": symbol,
                        "ok": True,
                        "step_size": rules["step_size"],
                        "tick_size": rules["tick_size"],
                        "min_notional": rules["min_notional"],
                    }
                )
            except Exception as exc:
                symbol_checks.append({"symbol": symbol, "ok": False, "error": str(exc)})
        add_check("whitelist_symbol_rules", ok=all(item["ok"] for item in symbol_checks), details={"symbols": symbol_checks})

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
