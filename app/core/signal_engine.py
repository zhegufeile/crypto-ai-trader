from app.ai.analyst import RuleBasedAnalyst
from app.ai.scorer import SignalScorer
from app.ai.validators import normalize_analysis
from app.config import Settings, get_settings
from app.core.risk_manager import RiskManager
from app.data.schema import Candidate, CandidateDiagnostic, StrategyMatchDiagnostic, TradeSignal
from app.knowledge.strategy_store import StrategyStore
from app.strategy.base import Strategy
from app.strategy.breakout import BreakoutStrategy
from app.strategy.momentum import MomentumStrategy
from app.strategy.pullback import PullbackStrategy
from app.strategy.sentiment import SentimentStrategy


class SignalEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        analyst: RuleBasedAnalyst | None = None,
        scorer: SignalScorer | None = None,
        risk_manager: RiskManager | None = None,
        strategies: list[Strategy] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.analyst = analyst or RuleBasedAnalyst()
        self.scorer = scorer or SignalScorer()
        self.risk_manager = risk_manager or RiskManager(self.settings)
        self.strategy_store = StrategyStore()
        self.strategies = strategies or [
            BreakoutStrategy(),
            MomentumStrategy(),
            PullbackStrategy(),
            SentimentStrategy(),
        ]

    def generate_signals(
        self,
        candidates: list[Candidate],
        open_positions: int = 0,
        realized_pnl_today: float = 0,
        strategy_tier_mode: str = "all",
        active_trades=None,
        recent_closed_trades=None,
    ) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        for candidate in candidates:
            self._apply_strategy_scores(candidate)
            self._apply_framework_scores(candidate)
            strategy_matches = self._apply_kol_cards(candidate, strategy_tier_mode=strategy_tier_mode)
            analysis = normalize_analysis(self.analyst.analyze(candidate))
            risk = self.risk_manager.evaluate(
                candidate,
                analysis,
                open_positions=open_positions + len(signals),
                realized_pnl_today=realized_pnl_today,
                active_trades=active_trades,
                recent_closed_trades=recent_closed_trades,
            )
            if not risk.allowed or not analysis.entry or not analysis.stop_loss or not analysis.take_profit:
                continue
            score = self.scorer.score(candidate, analysis)
            signals.append(
                TradeSignal(
                    symbol=analysis.symbol,
                    direction=analysis.direction,
                    confidence=analysis.confidence,
                    rr=analysis.rr,
                    score=score,
                    entry=analysis.entry,
                    stop_loss=analysis.stop_loss,
                    take_profit=analysis.take_profit,
                    structure=analysis.structure,
                    reasons=analysis.reason + risk.reasons,
                    management_plan=analysis.management_plan,
                    primary_strategy_name=strategy_matches[0].name if strategy_matches else None,
                    matched_strategy_names=[match.name for match in strategy_matches],
                )
            )
        return sorted(signals, key=lambda signal: signal.score, reverse=True)

    def diagnose_candidates(
        self,
        candidates: list[Candidate],
        open_positions: int = 0,
        realized_pnl_today: float = 0,
        strategy_tier_mode: str = "all",
    ) -> list[CandidateDiagnostic]:
        diagnostics: list[CandidateDiagnostic] = []
        accepted_count = 0
        for candidate in candidates:
            self._apply_strategy_scores(candidate)
            self._apply_framework_scores(candidate)
            strategy_matches = self._apply_kol_cards(candidate, strategy_tier_mode=strategy_tier_mode)
            analysis = normalize_analysis(self.analyst.analyze(candidate))
            risk = self.risk_manager.evaluate(
                candidate,
                analysis,
                open_positions=open_positions + accepted_count,
                realized_pnl_today=realized_pnl_today,
            )
            signal = None
            if risk.allowed and analysis.entry and analysis.stop_loss and analysis.take_profit:
                score = self.scorer.score(candidate, analysis)
                signal = TradeSignal(
                    symbol=analysis.symbol,
                    direction=analysis.direction,
                    confidence=analysis.confidence,
                    rr=analysis.rr,
                    score=score,
                    entry=analysis.entry,
                    stop_loss=analysis.stop_loss,
                    take_profit=analysis.take_profit,
                    structure=analysis.structure,
                    reasons=analysis.reason + risk.reasons,
                    management_plan=analysis.management_plan,
                )
                accepted_count += 1
            diagnostics.append(
                CandidateDiagnostic(
                    symbol=candidate.snapshot.symbol,
                    snapshot=candidate.snapshot,
                    hard_score=candidate.hard_score,
                    tags=list(dict.fromkeys(candidate.tags)),
                    reasons=candidate.reasons,
                    analysis=analysis,
                    risk=risk,
                    tradeable=signal is not None,
                    signal=signal,
                    strategy_tier_mode=strategy_tier_mode,
                    strategy_matches=strategy_matches,
                )
            )
        return sorted(
            diagnostics,
            key=lambda item: (
                1 if item.tradeable else 0,
                item.signal.score if item.signal else item.hard_score,
                item.hard_score,
            ),
            reverse=True,
        )

    def _apply_strategy_scores(self, candidate: Candidate) -> None:
        for strategy in self.strategies:
            score, reasons = strategy.score(candidate)
            if score:
                candidate.hard_score = min(candidate.hard_score + score, 100)
                candidate.tags.append(strategy.name)
                candidate.reasons.extend(reasons)

    def _apply_framework_scores(self, candidate: Candidate) -> None:
        snapshot = candidate.snapshot
        bonus = 0.0

        if snapshot.market_regime == "trend_or_acceleration":
            bonus += 10
            candidate.tags.append("regime:trend")
            candidate.reasons.append("market regime favors continuation")
        elif snapshot.market_regime == "uptrend_pullback":
            bonus += 8
            candidate.tags.append("regime:pullback")
            candidate.reasons.append("market regime favors cleaner pullback entries")
        elif snapshot.market_regime == "transition":
            bonus -= 6
            candidate.reasons.append("market regime is transitional and less clean")
        elif snapshot.market_regime == "range_or_chop":
            bonus -= 20
            candidate.tags.append("range_or_chop")
            candidate.reasons.append("market regime looks like late chop")

        if snapshot.relative_strength_score >= self.settings.min_relative_strength_score:
            bonus += 10
            candidate.tags.append("relative_strength_leader")
            candidate.reasons.append("relative strength is above baseline")
        elif snapshot.relative_strength_score <= 0.35:
            bonus -= 8
            candidate.reasons.append("relative strength is weak")

        if snapshot.follow_through_score >= self.settings.min_follow_through_score:
            bonus += 8
            candidate.tags.append("follow_through_good")
            candidate.reasons.append("follow-through quality supports expansion")
        elif "breakout" in candidate.tags or "momentum" in candidate.tags:
            bonus -= 12
            candidate.tags.append("failed_follow_through")
            candidate.reasons.append("breakout-style setup lacks follow-through quality")

        if snapshot.retest_quality_score >= self.settings.min_retest_quality_score:
            bonus += 7
            candidate.tags.append("good_retest")
            candidate.reasons.append("retest quality looks constructive")

        if snapshot.reversal_stage == "first_reversal":
            bonus += 6
            candidate.tags.append("first_reversal")
            candidate.reasons.append("setup still behaves like a first reversal")
        elif snapshot.reversal_stage == "late_reversal":
            bonus -= 12
            candidate.reasons.append("setup looks late in the reversal sequence")

        candidate.hard_score = min(max(candidate.hard_score + bonus, 0), 100)

    def _apply_kol_cards(
        self,
        candidate: Candidate,
        strategy_tier_mode: str = "all",
    ) -> list[StrategyMatchDiagnostic]:
        cards = self.strategy_store.list_cards()
        if not cards:
            return []

        matched_cards: list[tuple[str, str, float]] = []
        strategy_matches: list[StrategyMatchDiagnostic] = []
        bonus = 0.0
        for card in cards:
            if not card.matches(candidate.snapshot):
                continue
            card_tier = getattr(card, "strategy_tier", "watchlist")
            if not self._is_tier_enabled(card_tier, strategy_tier_mode):
                continue
            tier_multiplier = self._strategy_tier_multiplier(card_tier)
            card_bonus = max(card.confidence_bias * 20, 0)
            contribution_notes: list[str] = []
            symbol_match = candidate.snapshot.symbol in card.preferred_symbols
            if symbol_match:
                card_bonus += 8
                contribution_notes.append("preferred symbol matched")
            if card.market == "bullish" and candidate.snapshot.price_change_pct_24h >= 0:
                card_bonus += 4
                contribution_notes.append("bullish market bias aligned")
            if card.market == "bearish" and candidate.snapshot.price_change_pct_24h < 0:
                card_bonus += 4
                contribution_notes.append("bearish market bias aligned")
            if "trend_or_acceleration" in card.preferred_market_states and candidate.snapshot.btc_trend in {"up", "flat"}:
                card_bonus += 4
                contribution_notes.append("trend regime aligned")
            if "uptrend_pullback" in card.preferred_market_states and candidate.snapshot.price_change_pct_24h > 0:
                card_bonus += 4
                contribution_notes.append("pullback regime aligned")
            if "first_reversal_only" in card.entry_conditions:
                if candidate.snapshot.reversal_stage == "first_reversal":
                    card_bonus += 6
                    contribution_notes.append("first reversal condition satisfied")
                else:
                    card_bonus -= 8
                    candidate.reasons.append(f"{card.name} prefers the first clean reversal only")
                    contribution_notes.append("first reversal condition failed")
            if "relative_strength_leader" in card.entry_conditions:
                if candidate.snapshot.relative_strength_score >= self.settings.min_relative_strength_score:
                    card_bonus += 6
                    contribution_notes.append("relative strength leadership confirmed")
                else:
                    card_bonus -= 6
                    candidate.reasons.append(f"{card.name} expects clearer relative strength leadership")
                    contribution_notes.append("relative strength too weak")
            if len(card.entry_conditions) >= 2:
                card_bonus += 2
                contribution_notes.append("multi-condition setup bonus")
            if (
                "failed_follow_through_after_retest" in card.invalidation_conditions
                and candidate.snapshot.follow_through_score < self.settings.min_follow_through_score
            ):
                card_bonus -= 10
                candidate.reasons.append(f"{card.name} is invalidated by weak follow-through")
                contribution_notes.append("follow-through invalidation triggered")
            tier_score_bonus = min(max(getattr(card, "tier_score", 0.0), 0.0) * self.settings.tier_score_bonus_scale, 10.0)
            weighted_bonus = max(card_bonus, 0) * tier_multiplier + min(card_bonus, 0)
            weighted_bonus += tier_score_bonus
            bonus += weighted_bonus
            matched_cards.append((card.name, card_tier, weighted_bonus))
            strategy_matches.append(
                StrategyMatchDiagnostic(
                    name=card.name,
                    tier=card_tier,
                    tier_score=getattr(card, "tier_score", 0.0),
                    applied_bonus=round(weighted_bonus, 3),
                    weight_multiplier=tier_multiplier,
                    symbol_match=symbol_match,
                    notes=contribution_notes[:4],
                )
            )
            if card_tier == "core":
                candidate.reasons.append(f"{card.name} is in the core strategy pool")
            elif card_tier == "watchlist":
                candidate.reasons.append(f"{card.name} is still watchlist-grade and only adds light confirmation")
            candidate.reasons.extend(card.risk_notes[:2])

        if matched_cards:
            matched_cards.sort(key=lambda item: item[2], reverse=True)
            strategy_matches.sort(key=lambda item: item.applied_bonus, reverse=True)
            candidate.tags.extend([f"kol:{name}" for name, _, _ in matched_cards[:3]])
            candidate.tags.extend([f"strategy-tier:{tier}" for _, tier, _ in matched_cards[:2]])
            candidate.hard_score = min(candidate.hard_score + bonus, 100)
        return strategy_matches

    def _strategy_tier_multiplier(self, tier: str) -> float:
        if tier == "core":
            return self.settings.core_strategy_bonus_multiplier
        if tier == "candidate":
            return self.settings.candidate_strategy_bonus_multiplier
        return self.settings.watchlist_strategy_bonus_multiplier

    @staticmethod
    def _is_tier_enabled(tier: str, strategy_tier_mode: str) -> bool:
        if strategy_tier_mode == "core-only":
            return tier == "core"
        if strategy_tier_mode == "core+candidate":
            return tier in {"core", "candidate"}
        return True
