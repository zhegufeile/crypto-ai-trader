import asyncio
from collections.abc import Iterable

from app.config import Settings, get_settings
from app.data.binance_client import BinanceClient
from app.data.okx_client import OKXClient
from app.data.schema import Candidate, MarketSnapshot


class MarketCollector:
    def __init__(
        self,
        settings: Settings | None = None,
        client: BinanceClient | None = None,
        okx_client: OKXClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or BinanceClient(
            futures_base_url=self.settings.binance_base_url,
            spot_base_url=self.settings.binance_spot_base_url,
            proxy_url=self.settings.binance_proxy_url,
            proxy_fallback_enabled=self.settings.binance_proxy_fallback_enabled,
        )
        self.okx_client = okx_client or OKXClient(
            signal_snapshot_file=self.settings.onchain_signal_snapshot_file,
            risk_snapshot_file=self.settings.onchain_risk_snapshot_file,
        )

    async def collect_candidates(self) -> list[Candidate]:
        if hasattr(self.client, "session"):
            async with self.client.session() as request_session:
                tickers = await self.client.get_24h_tickers(client=request_session)
                btc_trend = self._btc_trend(tickers)
                raw_candidates = self._rank_tickers(tickers)
                semaphore = asyncio.Semaphore(max(1, self.settings.snapshot_fetch_concurrency))

                async def build_with_limit(ticker: dict) -> MarketSnapshot:
                    async with semaphore:
                        return await self._build_snapshot(ticker, btc_trend, request_session)

                snapshots = await asyncio.gather(
                    *(build_with_limit(ticker) for ticker in raw_candidates),
                    return_exceptions=True,
                )
        else:
            tickers = await self.client.get_24h_tickers()
            btc_trend = self._btc_trend(tickers)
            raw_candidates = self._rank_tickers(tickers)
            semaphore = asyncio.Semaphore(max(1, self.settings.snapshot_fetch_concurrency))

            async def build_with_limit(ticker: dict) -> MarketSnapshot:
                async with semaphore:
                    return await self._build_snapshot(ticker, btc_trend)

            snapshots = await asyncio.gather(
                *(build_with_limit(ticker) for ticker in raw_candidates),
                return_exceptions=True,
            )
        candidates = [
            self._score_snapshot(snapshot)
            for snapshot in snapshots
            if isinstance(snapshot, MarketSnapshot)
        ]
        if self.settings.enable_onchain_signal_boost and candidates:
            signal_map = await self.okx_client.get_symbol_signal_map([item.snapshot.symbol for item in candidates])
            candidates = [self._apply_onchain_signal(candidate, signal_map) for candidate in candidates]
            risk_map = await self.okx_client.get_symbol_risk_map([item.snapshot.symbol for item in candidates])
            candidates = [self._apply_onchain_risk(candidate, risk_map) for candidate in candidates]
        return sorted(candidates, key=lambda item: item.hard_score, reverse=True)[
            : self.settings.max_candidates
        ]

    def _rank_tickers(self, tickers: Iterable[dict]) -> list[dict]:
        ranked: list[dict] = []
        for ticker in tickers:
            symbol = str(ticker.get("symbol", ""))
            quote_volume = float(ticker.get("quoteVolume", 0) or 0)
            if not symbol.endswith("USDT") or symbol in self.settings.blacklisted_symbols:
                continue
            if quote_volume < self.settings.min_volume_usdt:
                continue
            ranked.append(ticker)
        return sorted(
            ranked,
            key=lambda item: abs(float(item.get("priceChangePercent", 0) or 0))
            * float(item.get("quoteVolume", 0) or 0),
            reverse=True,
        )[: max(self.settings.max_candidates * self.settings.candidate_buffer_multiplier, self.settings.max_candidates)]

    async def _build_snapshot(
        self,
        ticker: dict,
        btc_trend: str,
        client=None,
    ) -> MarketSnapshot:
        symbol = ticker["symbol"]
        if client is None:
            oi_task = self.client.get_open_interest(symbol)
            premium_task = self.client.get_premium_index(symbol)
            ratio_task = self.client.get_long_short_ratio(symbol, limit=1)
            taker_task = self.client.get_taker_buy_sell_ratio(symbol, limit=1)
        else:
            oi_task = self.client.get_open_interest(symbol, client=client)
            premium_task = self.client.get_premium_index(symbol, client=client)
            ratio_task = self.client.get_long_short_ratio(symbol, limit=1, client=client)
            taker_task = self.client.get_taker_buy_sell_ratio(symbol, limit=1, client=client)
        oi, premium, ratios, taker_ratios = await asyncio.gather(
            oi_task, premium_task, ratio_task, taker_task, return_exceptions=True
        )
        latest_ratio = ratios[-1] if isinstance(ratios, list) and ratios else {}
        latest_taker = taker_ratios[-1] if isinstance(taker_ratios, list) and taker_ratios else {}
        price_change_pct = float(ticker.get("priceChangePercent", 0) or 0)
        quote_volume_24h = float(ticker.get("quoteVolume", 0) or 0)
        oi_value = float(oi.get("openInterest", 0) or 0) if isinstance(oi, dict) else None
        funding_rate = float(premium.get("lastFundingRate", 0) or 0) if isinstance(premium, dict) else None
        long_short_ratio = float(latest_ratio.get("longShortRatio", 0) or 0)
        taker_buy_sell_ratio = float(latest_taker.get("buySellRatio", 0) or 0)
        relative_strength_score = self._relative_strength_score(
            price_change_pct=price_change_pct,
            quote_volume_24h=quote_volume_24h,
            taker_buy_sell_ratio=taker_buy_sell_ratio,
            btc_trend=btc_trend,
            funding_rate=funding_rate,
        )
        retest_quality_score = self._retest_quality_score(
            price_change_pct=price_change_pct,
            btc_trend=btc_trend,
            funding_rate=funding_rate,
            taker_buy_sell_ratio=taker_buy_sell_ratio,
        )
        follow_through_score = self._follow_through_score(
            price_change_pct=price_change_pct,
            quote_volume_24h=quote_volume_24h,
            oi=oi_value,
            taker_buy_sell_ratio=taker_buy_sell_ratio,
        )
        market_regime = self._market_regime(
            price_change_pct=price_change_pct,
            btc_trend=btc_trend,
            taker_buy_sell_ratio=taker_buy_sell_ratio,
            quote_volume_24h=quote_volume_24h,
        )
        reversal_stage = self._reversal_stage(
            price_change_pct=price_change_pct,
            btc_trend=btc_trend,
            market_regime=market_regime,
            taker_buy_sell_ratio=taker_buy_sell_ratio,
        )
        return MarketSnapshot(
            symbol=symbol,
            price=float(ticker.get("lastPrice", 0) or 0),
            volume_24h=float(ticker.get("volume", 0) or 0),
            quote_volume_24h=quote_volume_24h,
            price_change_pct_24h=price_change_pct,
            oi=oi_value,
            funding_rate=funding_rate,
            long_short_ratio=long_short_ratio,
            taker_buy_sell_ratio=taker_buy_sell_ratio,
            btc_trend=btc_trend,
            market_regime=market_regime,
            reversal_stage=reversal_stage,
            relative_strength_score=relative_strength_score,
            sector_strength_score=relative_strength_score,
            retest_quality_score=retest_quality_score,
            follow_through_score=follow_through_score,
        )

    def _score_snapshot(self, snapshot: MarketSnapshot) -> Candidate:
        reasons: list[str] = []
        tags: list[str] = []
        score = 0.0

        abs_change = abs(snapshot.price_change_pct_24h)
        if abs_change >= 4:
            score += 25
            tags.append("momentum")
            reasons.append("24h price movement is strong")
        if snapshot.quote_volume_24h >= self.settings.min_volume_usdt * 2:
            score += 25
            tags.append("high_liquidity")
            reasons.append("quote volume is above liquidity threshold")
        if snapshot.oi and snapshot.oi > 0:
            score += 15
            tags.append("oi_available")
            reasons.append("open interest is available")
        if snapshot.funding_rate is not None and abs(snapshot.funding_rate) < 0.001:
            score += 10
            tags.append("funding_not_overheated")
            reasons.append("funding rate is not overheated")
        if snapshot.long_short_ratio and 0.75 <= snapshot.long_short_ratio <= 1.8:
            score += 10
            reasons.append("long/short ratio is within tradable range")
        if snapshot.btc_trend in {"up", "flat"}:
            score += 15
            reasons.append("BTC background is not hostile")
        if snapshot.market_regime in {"trend_or_acceleration", "uptrend_pullback"}:
            score += 10
            tags.append("clean_regime")
            reasons.append("market regime is cleaner than late chop")
        if snapshot.relative_strength_score >= self.settings.min_relative_strength_score:
            score += 10
            tags.append("relative_strength_leader")
            reasons.append("symbol is acting stronger than baseline")
        if snapshot.follow_through_score >= self.settings.min_follow_through_score:
            score += 8
            tags.append("follow_through_good")
            reasons.append("post-trigger follow-through looks healthier")
        if snapshot.retest_quality_score >= self.settings.min_retest_quality_score:
            score += 7
            tags.append("good_retest")
            reasons.append("retest quality is constructive")
        if snapshot.reversal_stage == "first_reversal":
            score += 5
            tags.append("first_reversal")
            reasons.append("setup still looks like a first reversal instead of late chop")

        return Candidate(snapshot=snapshot, hard_score=min(score, 100), tags=tags, reasons=reasons)

    def _apply_onchain_signal(
        self,
        candidate: Candidate,
        signal_map: dict[str, dict],
    ) -> Candidate:
        snapshot = candidate.snapshot
        base_symbol = self._base_symbol(snapshot.symbol)
        signal = signal_map.get(base_symbol)
        if not signal:
            return candidate

        snapshot.onchain_signal_score = float(signal.get("signal_score", 0) or 0)
        snapshot.onchain_wallet_count = int(signal.get("wallet_count", 0) or 0)
        snapshot.onchain_buy_amount_usd = float(signal.get("buy_amount_usd", 0) or 0)
        snapshot.onchain_sold_ratio_percent = signal.get("sold_ratio_percent")
        snapshot.onchain_wallet_types = list(signal.get("wallet_types", []) or [])

        bonus = 0.0
        if snapshot.onchain_signal_score >= self.settings.min_onchain_signal_score:
            bonus += 12
            candidate.tags.append("onchain_signal")
            candidate.reasons.append("onchain smart-money or KOL flow supports the setup")
        if snapshot.onchain_wallet_count >= 3:
            bonus += 8
            candidate.tags.append("multi_wallet_confirmation")
            candidate.reasons.append("multiple tracked wallets hit the same token")
        if snapshot.onchain_buy_amount_usd >= 50_000:
            bonus += 6
            candidate.reasons.append("onchain buy amount is large enough to matter")
        if snapshot.onchain_sold_ratio_percent is not None and snapshot.onchain_sold_ratio_percent <= 35:
            bonus += 5
            candidate.reasons.append("tracked wallets are still largely holding")
        elif snapshot.onchain_sold_ratio_percent is not None and snapshot.onchain_sold_ratio_percent >= 70:
            bonus -= 8
            candidate.reasons.append("tracked wallets have already largely sold the move")
        if any(wallet_type.lower() in {"smart money", "smart_money", "1"} for wallet_type in snapshot.onchain_wallet_types):
            bonus += 4
        if any(wallet_type.lower() in {"kol", "influencer", "2"} for wallet_type in snapshot.onchain_wallet_types):
            bonus += 3
        if any(wallet_type.lower() in {"whale", "3"} for wallet_type in snapshot.onchain_wallet_types):
            bonus += 3

        candidate.hard_score = min(max(candidate.hard_score + bonus, 0), 100)
        return candidate

    def _apply_onchain_risk(
        self,
        candidate: Candidate,
        risk_map: dict[str, dict],
    ) -> Candidate:
        snapshot = candidate.snapshot
        base_symbol = self._base_symbol(snapshot.symbol)
        risk = risk_map.get(base_symbol)
        if not risk:
            return candidate

        snapshot.onchain_risk_level = str(risk.get("risk_level", "unknown"))
        snapshot.onchain_risk_tags = list(risk.get("risk_tags", []) or [])
        snapshot.onchain_honeypot = bool(risk.get("honeypot"))
        snapshot.onchain_is_safe_buy = risk.get("is_safe_buy")
        snapshot.onchain_top10_holder_percent = risk.get("top10_holder_percent")
        snapshot.onchain_dev_holding_percent = risk.get("dev_holding_percent")
        snapshot.onchain_bundle_holding_percent = risk.get("bundle_holding_percent")
        snapshot.onchain_suspicious_holding_percent = risk.get("suspicious_holding_percent")
        snapshot.onchain_liquidity_usd = risk.get("liquidity_usd")

        risk_level = snapshot.onchain_risk_level.upper()
        risk_tags = {tag.lower() for tag in snapshot.onchain_risk_tags}
        penalty = 0.0

        if snapshot.onchain_honeypot or snapshot.onchain_is_safe_buy is False:
            penalty -= 100
            candidate.tags.append("blocked:honeypot")
            candidate.reasons.append("onchain security marks this token as honeypot or unsafe to buy")
        if risk_level == "CRITICAL":
            penalty -= 100
            candidate.tags.append("blocked:critical_risk")
            candidate.reasons.append("onchain risk level is critical")
        elif risk_level == "HIGH":
            penalty -= 40
            candidate.reasons.append("onchain risk level is high")
        elif risk_level in {"3", "4", "5"}:
            penalty -= 35
            candidate.reasons.append("token risk control level is elevated")

        if "honeypot" in risk_tags:
            penalty -= 100
            candidate.reasons.append("token carries a honeypot tag")
        if "lowliquidity" in risk_tags:
            penalty -= 20
            candidate.reasons.append("token is tagged as low liquidity")
        if "devholdingstatussellall" in risk_tags:
            penalty -= 18
            candidate.reasons.append("developer has already sold all holdings")
        if "devholdingstatussell" in risk_tags:
            penalty -= 12
            candidate.reasons.append("developer is actively selling")

        if snapshot.onchain_liquidity_usd is not None and snapshot.onchain_liquidity_usd < 10_000:
            penalty -= 25
            candidate.reasons.append("onchain liquidity is too low")
        if snapshot.onchain_top10_holder_percent is not None and snapshot.onchain_top10_holder_percent >= 85:
            penalty -= 20
            candidate.reasons.append("top 10 holders are too concentrated")
        if snapshot.onchain_dev_holding_percent is not None and snapshot.onchain_dev_holding_percent >= 20:
            penalty -= 16
            candidate.reasons.append("developer holding percentage is too high")
        if snapshot.onchain_bundle_holding_percent is not None and snapshot.onchain_bundle_holding_percent >= 15:
            penalty -= 14
            candidate.reasons.append("bundle holding percentage is too high")
        if snapshot.onchain_suspicious_holding_percent is not None and snapshot.onchain_suspicious_holding_percent >= 10:
            penalty -= 18
            candidate.reasons.append("suspicious holding percentage is too high")

        if penalty:
            candidate.tags.append("onchain_risk_checked")
            candidate.hard_score = min(max(candidate.hard_score + penalty, 0), 100)
        return candidate

    @staticmethod
    def _btc_trend(tickers: Iterable[dict]) -> str:
        for ticker in tickers:
            if ticker.get("symbol") == "BTCUSDT":
                change = float(ticker.get("priceChangePercent", 0) or 0)
                if change > 1:
                    return "up"
                if change < -1:
                    return "down"
                return "flat"
        return "unknown"

    @staticmethod
    def _relative_strength_score(
        price_change_pct: float,
        quote_volume_24h: float,
        taker_buy_sell_ratio: float | None,
        btc_trend: str,
        funding_rate: float | None,
    ) -> float:
        score = 0.45
        if price_change_pct > 4:
            score += 0.18
        elif price_change_pct > 1.5:
            score += 0.10
        if quote_volume_24h > 100_000_000:
            score += 0.12
        if taker_buy_sell_ratio and taker_buy_sell_ratio > 1.05:
            score += 0.12
        if btc_trend in {"up", "flat"}:
            score += 0.06
        if funding_rate is not None and abs(funding_rate) < 0.001:
            score += 0.04
        return round(max(0.0, min(score, 1.0)), 3)

    @staticmethod
    def _retest_quality_score(
        price_change_pct: float,
        btc_trend: str,
        funding_rate: float | None,
        taker_buy_sell_ratio: float | None,
    ) -> float:
        score = 0.35
        if 1.5 <= abs(price_change_pct) <= 6:
            score += 0.20
        if btc_trend in {"up", "flat"}:
            score += 0.12
        if taker_buy_sell_ratio and 1.0 <= taker_buy_sell_ratio <= 1.2:
            score += 0.15
        if funding_rate is not None and abs(funding_rate) < 0.001:
            score += 0.08
        return round(max(0.0, min(score, 1.0)), 3)

    @staticmethod
    def _follow_through_score(
        price_change_pct: float,
        quote_volume_24h: float,
        oi: float | None,
        taker_buy_sell_ratio: float | None,
    ) -> float:
        score = 0.3
        if abs(price_change_pct) >= 4:
            score += 0.18
        if quote_volume_24h > 100_000_000:
            score += 0.18
        if oi and oi > 0:
            score += 0.12
        if taker_buy_sell_ratio and taker_buy_sell_ratio > 1.04:
            score += 0.16
        return round(max(0.0, min(score, 1.0)), 3)

    @staticmethod
    def _market_regime(
        price_change_pct: float,
        btc_trend: str,
        taker_buy_sell_ratio: float | None,
        quote_volume_24h: float,
    ) -> str:
        if abs(price_change_pct) < 1.2 and (taker_buy_sell_ratio is None or 0.98 <= taker_buy_sell_ratio <= 1.02):
            return "range_or_chop"
        if abs(price_change_pct) >= 4 and quote_volume_24h > 100_000_000:
            return "trend_or_acceleration"
        if 1.5 <= abs(price_change_pct) <= 4 and btc_trend in {"up", "flat"}:
            return "uptrend_pullback"
        return "transition"

    @staticmethod
    def _reversal_stage(
        price_change_pct: float,
        btc_trend: str,
        market_regime: str,
        taker_buy_sell_ratio: float | None,
    ) -> str:
        if market_regime == "range_or_chop":
            return "late_reversal"
        if btc_trend == "down" and price_change_pct > 2 and (taker_buy_sell_ratio or 0) > 1.03:
            return "first_reversal"
        if btc_trend == "up" and price_change_pct < -2 and (taker_buy_sell_ratio or 9) < 0.97:
            return "first_reversal"
        return "trend"

    @staticmethod
    def _base_symbol(symbol: str) -> str:
        cleaned = symbol.upper()
        for quote in ("USDT", "USDC", "USD", "PERP"):
            if cleaned.endswith(quote) and len(cleaned) > len(quote):
                return cleaned[: -len(quote)]
        return cleaned
