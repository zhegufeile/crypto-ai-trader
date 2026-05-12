from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import get_settings
from app.core.simulator import ACTIVE_TRADE_STATUSES
from app.storage.db import get_session
from app.storage.repositories import TradeFeeRepository, TradeRepository

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/summary")
def get_account_summary(session: Session = Depends(get_session)) -> dict:
    settings = get_settings()
    trades = TradeRepository(session).list_all_trades(limit=1000)
    fee_repo = TradeFeeRepository(session)
    active = [trade for trade in trades if trade.status in ACTIVE_TRADE_STATUSES]
    closed = [trade for trade in trades if trade.status in {"closed", "cancelled"}]
    pending = [trade for trade in trades if trade.status == "pending_entry"]

    realized_pnl = round(sum(trade.realized_pnl_usdt for trade in trades), 4)
    unrealized_pnl = round(sum(trade.unrealized_pnl_usdt for trade in active), 4)
    equity = round(settings.simulation_starting_balance_usdt + realized_pnl + unrealized_pnl, 4)
    capital_in_use = round(sum(trade.remaining_notional_usdt for trade in active), 4)
    available_balance = round(equity - capital_in_use, 4)

    cutoff_24h = datetime.now(UTC) - timedelta(hours=24)
    total_fees = round(fee_repo.sum_all(), 4)
    fees_24h = round(fee_repo.sum_since(cutoff_24h), 4)
    realized_pnl_24h = round(
        sum(
            trade.realized_pnl_usdt
            for trade in closed
            if (trade.closed_at or trade.updated_at or trade.opened_at) >= cutoff_24h
        ),
        4,
    )

    winning_closed = [trade for trade in closed if trade.realized_pnl_usdt > 0]
    closed_count = len(closed)
    win_rate = round((len(winning_closed) / closed_count), 4) if closed_count else 0.0

    equity_curve = _build_equity_curve(
        starting_balance=settings.simulation_starting_balance_usdt,
        closed_trades=closed,
        current_equity=equity,
    )

    return {
        "mode": "simulation" if settings.use_simulation else "live",
        "starting_balance_usdt": round(settings.simulation_starting_balance_usdt, 4),
        "equity_usdt": equity,
        "available_balance_usdt": available_balance,
        "capital_in_use_usdt": capital_in_use,
        "realized_pnl_usdt": realized_pnl,
        "unrealized_pnl_usdt": unrealized_pnl,
        "total_pnl_usdt": round(realized_pnl + unrealized_pnl, 4),
        "total_fees_usdt": total_fees,
        "fees_24h_usdt": fees_24h,
        "realized_pnl_24h_usdt": realized_pnl_24h,
        "open_positions": len([trade for trade in active if trade.status in {"open", "partial"}]),
        "pending_positions": len(pending),
        "closed_trades": closed_count,
        "win_rate": win_rate,
        "equity_curve": equity_curve,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _build_equity_curve(*, starting_balance: float, closed_trades: list, current_equity: float) -> list[dict]:
    if not closed_trades:
        return [{"time": datetime.now(UTC).isoformat(), "equity": round(current_equity, 4)}]

    ordered = sorted(
        closed_trades,
        key=lambda trade: trade.closed_at or trade.updated_at or trade.opened_at,
    )
    running = float(starting_balance)
    points: list[dict] = []
    for trade in ordered[-40:]:
        running += float(trade.realized_pnl_usdt)
        points.append(
            {
                "time": (trade.closed_at or trade.updated_at or trade.opened_at).isoformat(),
                "equity": round(running, 4),
            }
        )

    if not points or points[-1]["equity"] != round(current_equity, 4):
        points.append({"time": datetime.now(UTC).isoformat(), "equity": round(current_equity, 4)})
    return points
