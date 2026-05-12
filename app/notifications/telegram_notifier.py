import httpx

from app.config import Settings, get_settings
from app.data.schema import TradeSignal


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_signal(self, signal: TradeSignal) -> bool:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            return False
        text = (
            f"Signal {signal.symbol} {signal.direction.value}\n"
            f"score={signal.score} confidence={signal.confidence:.2f} rr={signal.rr:.2f}\n"
            f"entry={signal.entry:.6g} sl={signal.stop_loss:.6g} tp={signal.take_profit:.6g}"
        )
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={"chat_id": self.settings.telegram_chat_id, "text": text},
            )
            response.raise_for_status()
        return True
