from app.data.schema import TradeSignal


class EmailNotifier:
    async def send_signal(self, signal: TradeSignal) -> bool:
        return False
