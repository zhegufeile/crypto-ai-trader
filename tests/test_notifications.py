import pytest

from app.config import Settings
from app.data.schema import Direction, StructureType, TradeSignal
from app.notifications.telegram_notifier import TelegramNotifier


@pytest.mark.asyncio
async def test_telegram_notifier_noops_without_config():
    signal = TradeSignal(
        symbol="BTCUSDT",
        direction=Direction.LONG,
        confidence=0.8,
        rr=2.5,
        score=88,
        entry=100,
        stop_loss=95,
        take_profit=112,
        structure=StructureType.BREAKOUT,
    )

    sent = await TelegramNotifier(Settings(telegram_bot_token=None, telegram_chat_id=None)).send_signal(
        signal
    )

    assert sent is False
