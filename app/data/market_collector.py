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

    async def collect_symbol_snapshot(self, symbol: str) -> MarketSnapshot | None:
        symbol = symbol.upper()
        if hasattr(self.client, "session"):
            async with self.client.session() as request_session:
                tickers = await self.client.get_24h_tickers(client=request_session)
                ticker = self._ticker_for_symbol(tickers, symbol)
                if ticker is None:
                    return None
                return await self._build_snapshot(ticker, self._btc_trend(tickers), request_session)

        tickers = await self.client.get_24h_tickers()
        ticker = self._ticker_for_symbol(tickers, symbol)
        if ticker is None:
            return None
        return await self._build_snapshot(ticker, self._btc_trend(tickers))

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

    @staticmethod
    def _ticker_for_symbol(tickers: Iterable[dict], symbol: str) -> dict | None:
        for ticker in tickers:
            if str(ticker.get("symbol", "")).upper() == symbol:
                return ticker
        return None

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
            klines_5m_task = self._maybe_get_klines(symbol, interval="5m", limit=30)
            klines_1h_task = self._maybe_get_klines(symbol, interval="1h", limit=60)
            klines_4h_task = self._maybe_get_klines(symbol, interval="4h", limit=60)
        else:
            oi_task = self.client.get_open_interest(symbol, client=client)
            premium_task = self.client.get_premium_index(symbol, client=client)
            ratio_task = self.client.get_long_short_ratio(symbol, limit=1, client=client)
            taker_task = self.client.get_taker_buy_sell_ratio(symbol, limit=1, client=client)
            klines_5m_task = self._maybe_get_klines(symbol, interval="5m", limit=30, client=client)
            klines_1h_task = self._maybe_get_klines(symbol, interval="1h", limit=60, client=client)
            klines_4h_task = self._maybe_get_klines(symbol, interval="4h", limit=60, client=client)
        oi, premium, ratios, taker_ratios, klines_5m, klines_1h, klines_4h = await asyncio.gather(
            oi_task,
            premium_task,
            ratio_task,
            taker_task,
            klines_5m_task,
            klines_1h_task,
            klines_4h_task,
            return_exceptions=True,
        )
        latest_ratio = ratios[-1] if isinstance(ratios, list) and ratios and isinstance(ratios[-1], dict) else {}
        latest_taker = taker_ratios[-1] if isinstance(taker_ratios, list) and taker_ratios and isinstance(taker_ratios[-1], dict) else {}
        price_change_pct = float(ticker.get("priceChangePercent", 0) or 0)
        quote_volume_24h = float(ticker.get("quoteVolume", 0) or 0)
        oi_value = float(oi.get("openInterest", 0) or 0) if isinstance(oi, dict) else None
        funding_rate = float(premium.get("lastFundingRate", 0) or 0) if isinstance(premium, dict) else None
        long_short_ratio = float(latest_ratio.get("longShortRatio", 0) or 0)
        taker_buy_sell_ratio = float(latest_taker.get("buySellRatio", 0) or 0)
        context = self._derive_execution_context(
            price=float(ticker.get("lastPrice", 0) or 0),
            price_change_pct=price_change_pct,
            klines_5m=self._safe_klines(klines_5m),
            klines_1h=self._safe_klines(klines_1h),
            klines_4h=self._safe_klines(klines_4h),
        )
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
        if context["distance_from_breakout_level_atr"] <= 0.35:
            retest_quality_score = min(1.0, round(retest_quality_score + 0.08, 3))
        follow_through_score = self._follow_through_score(
            price_change_pct=price_change_pct,
            quote_volume_24h=quote_volume_24h,
            oi=oi_value,
            taker_buy_sell_ratio=taker_buy_sell_ratio,
        )
        if context["breakout_acceptance_score"] >= 0.65:
            follow_through_score = min(1.0, round(follow_through_score + 0.06, 3))
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
            htf_trend_bias=context["htf_trend_bias"],
            breakout_acceptance_score=context["breakout_acceptance_score"],
            relative_volume_ratio=context["relative_volume_ratio"],
            atr=context["atr"],
            distance_from_vwap_atr=context["distance_from_vwap_atr"],
            distance_from_breakout_level_atr=context["distance_from_breakout_level_atr"],
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
        if snapshot.breakout_acceptance_score is not None and snapshot.breakout_acceptance_score >= self.settings.min_breakout_acceptance_score:
            score += 6
            tags.append("confirmed_breakout")
            reasons.append("breakout acceptance is being sustained")
        if snapshot.relative_volume_ratio is not None and snapshot.relative_volume_ratio >= self.settings.min_relative_volume_ratio:
            score += 5
            tags.append("relative_volume_confirmed")
            reasons.append("relative volume confirms the active move")
        if snapshot.htf_trend_bias is not None and snapshot.htf_trend_bias >= self.settings.min_htf_trend_bias:
            score += 6
            tags.append("htf_bullish")
            reasons.append("higher timeframe trend is aligned")
        elif snapshot.htf_trend_bias is not None and snapshot.htf_trend_bias <= -self.settings.min_htf_trend_bias:
            score += 3
            tags.append("htf_bearish")
            reasons.append("higher timeframe trend is cleanly bearish")
        if snapshot.distance_from_vwap_atr is not None and snapshot.distance_from_vwap_atr > self.settings.max_distance_from_vwap_atr:
            score -= 8
            tags.append("overextended_from_vwap")
            reasons.append("price is already extended away from VWAP")
        if (
            snapshot.distance_from_breakout_level_atr is not None
            and snapshot.distance_from_breakout_level_atr > self.settings.max_distance_from_breakout_level_atr
        ):
            score -= 8
            tags.append("late_breakout_extension")
            reasons.append("entry is getting too far from the breakout level")
        if snapshot.reversal_stage == "first_reversal":
            score += 5
            tags.append("first_reversal")
            reasons.append("setup still looks like a first reversal instead of late chop")

        return Candidate(snapshot=snapshot, hard_score=min(max(score, 0), 100), tags=tags, reasons=reasons)

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
    async def _empty_klines() -> list[list]:
        return []

    def _maybe_get_klines(self, symbol: str, interval: str, limit: int, client=None):
        get_klines = getattr(self.client, "get_klines", None)
        if get_klines is None:
            return self._empty_klines()
        if client is None:
            return get_klines(symbol, interval=interval, limit=limit)
        return get_klines(symbol, interval=interval, limit=limit, client=client)

    @staticmethod
    def _safe_klines(payload) -> list[list]:
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, list)]

    @staticmethod
    def _derive_execution_context(
        price: float,
        price_change_pct: float,
        klines_5m: list[list],
        klines_1h: list[list],
        klines_4h: list[list],
    ) -> dict[str, float]:
        relative_volume_ratio = MarketCollector._relative_volume_ratio(klines_5m)
        atr = MarketCollector._atr(klines_5m)
        vwap = MarketCollector._vwap(klines_5m)
        breakout_level = MarketCollector._breakout_level(klines_5m, price_change_pct)
        distance_from_vwap_atr = abs(price - vwap) / atr if atr > 0 and vwap > 0 else 0.0
        distance_from_breakout_level_atr = abs(price - breakout_level) / atr if atr > 0 and breakout_level > 0 else 0.0
        breakout_acceptance_score = MarketCollector._breakout_acceptance_score(
            price=price,
            price_change_pct=price_change_pct,
            breakout_level=breakout_level,
            atr=atr,
            relative_volume_ratio=relative_volume_ratio,
            klines_5m=klines_5m,
        )
        return {
            "htf_trend_bias": MarketCollector._htf_trend_bias(klines_1h, klines_4h),
            "breakout_acceptance_score": breakout_acceptance_score,
            "relative_volume_ratio": round(relative_volume_ratio, 3),
            "atr": round(atr, 8),
            "distance_from_vwap_atr": round(distance_from_vwap_atr, 3),
            "distance_from_breakout_level_atr": round(distance_from_breakout_level_atr, 3),
        }

    @staticmethod
    def _relative_volume_ratio(klines: list[list]) -> float:
        if len(klines) < 6:
            return 1.0
        volumes = [float(item[5]) for item in klines if len(item) > 5]
        if len(volumes) < 6:
            return 1.0
        baseline = sum(volumes[:-1]) / max(len(volumes[:-1]), 1)
        if baseline <= 0:
            return 1.0
        return max(volumes[-1] / baseline, 0.0)

    @staticmethod
    def _atr(klines: list[list], period: int = 14) -> float:
        if len(klines) < 2:
            return 0.0
        true_ranges: list[float] = []
        prev_close = float(klines[0][4])
        for candle in klines[1:]:
            high = float(candle[2])
            low = float(candle[3])
            close = float(candle[4])
            true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
            prev_close = close
        window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
        if not window:
            return 0.0
        return sum(window) / len(window)

    @staticmethod
    def _vwap(klines: list[list]) -> float:
        if not klines:
            return 0.0
        pv = 0.0
        volume = 0.0
        for candle in klines:
            typical = (float(candle[2]) + float(candle[3]) + float(candle[4])) / 3
            candle_volume = float(candle[5])
            pv += typical * candle_volume
            volume += candle_volume
        if volume <= 0:
            return 0.0
        return pv / volume

    @staticmethod
    def _breakout_level(klines: list[list], price_change_pct: float) -> float:
        if len(klines) < 6:
            return 0.0
        lookback = klines[:-1][-20:]
        if not lookback:
            return 0.0
        if price_change_pct >= 0:
            return max(float(candle[2]) for candle in lookback)
        return min(float(candle[3]) for candle in lookback)

    @staticmethod
    def _breakout_acceptance_score(
        price: float,
        price_change_pct: float,
        breakout_level: float,
        atr: float,
        relative_volume_ratio: float,
        klines_5m: list[list],
    ) -> float:
        if breakout_level <= 0 or atr <= 0 or len(klines_5m) < 3:
            return 0.5
        recent_closes = [float(candle[4]) for candle in klines_5m[-3:]]
        if price_change_pct >= 0:
            accepted = sum(1 for close in recent_closes if close >= breakout_level)
            distance_bonus = max(0.0, 1 - max(price - breakout_level, 0.0) / (atr * 1.5))
        else:
            accepted = sum(1 for close in recent_closes if close <= breakout_level)
            distance_bonus = max(0.0, 1 - max(breakout_level - price, 0.0) / (atr * 1.5))
        score = 0.25 + accepted * 0.18 + min(relative_volume_ratio, 2.0) * 0.12 + distance_bonus * 0.18
        return round(max(0.0, min(score, 1.0)), 3)

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        if not values:
            return 0.0
        alpha = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = value * alpha + ema * (1 - alpha)
        return ema

    @staticmethod
    def _htf_trend_bias(klines_1h: list[list], klines_4h: list[list]) -> float:
        bias = 0.0
        for klines, weight in ((klines_1h, 0.45), (klines_4h, 0.45)):
            closes = [float(item[4]) for item in klines if len(item) > 4]
            if len(closes) < 20:
                continue
            ema20 = MarketCollector._ema(closes[-20:], min(20, len(closes[-20:])))
            ema50 = MarketCollector._ema(closes[-50:], min(50, len(closes[-50:])))
            last_close = closes[-1]
            if last_close >= ema20 >= ema50:
                bias += weight
            elif last_close <= ema20 <= ema50:
                bias -= weight
        if len(klines_1h) >= 6:
            closes_1h = [float(item[4]) for item in klines_1h if len(item) > 4]
            if closes_1h[-1] > closes_1h[-6]:
                bias += 0.1
            elif closes_1h[-1] < closes_1h[-6]:
                bias -= 0.1
        return round(max(-1.0, min(bias, 1.0)), 3)

    @staticmethod
    def _base_symbol(symbol: str) -> str:
        cleaned = symbol.upper()
        for quote in ("USDT", "USDC", "USD", "PERP"):
            if cleaned.endswith(quote) and len(cleaned) > len(quote):
                return cleaned[: -len(quote)]
        return cleaned
