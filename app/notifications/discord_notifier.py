import httpx

from app.config import Settings, get_settings
from app.data.schema import TradeSignal


class DiscordNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send_signal(self, signal: TradeSignal) -> bool:
        if not self.settings.discord_webhook_url:
            return False
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.settings.discord_webhook_url,
                json={"content": f"{signal.symbol} {signal.direction.value} score={signal.score}"},
            )
            response.raise_for_status()
        return True
