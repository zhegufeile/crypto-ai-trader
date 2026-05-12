from app.data.schema import AnalysisResult, Candidate, Direction, StructureType


class RuleBasedAnalyst:
    """Deterministic analyst used until an LLM key and prompt workflow are configured."""

    def analyze(self, candidate: Candidate) -> AnalysisResult:
        snapshot = candidate.snapshot
        direction = Direction.LONG if snapshot.price_change_pct_24h >= 0 else Direction.SHORT
        structure = self._infer_structure(candidate)
        confidence = self._estimate_confidence(candidate)
        rr = self._estimate_rr(candidate)
        entry = snapshot.price
        stop_pct = self._stop_pct(candidate, structure)
        target_pct = stop_pct * rr
        management_plan = self._management_plan(candidate, structure)
        if direction == Direction.LONG:
            stop_loss = entry * (1 - stop_pct)
            take_profit = entry * (1 + target_pct)
        else:
            stop_loss = entry * (1 + stop_pct)
            take_profit = entry * (1 - target_pct)
        return AnalysisResult(
            symbol=snapshot.symbol,
            structure=structure,
            direction=direction,
            confidence=confidence,
            rr=rr,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=candidate.reasons,
            management_plan=management_plan,
        )

    @staticmethod
    def _infer_structure(candidate: Candidate) -> StructureType:
        change = candidate.snapshot.price_change_pct_24h
        if change >= 4:
            return StructureType.BREAKOUT
        if abs(change) >= 6:
            return StructureType.MOMENTUM
        if abs(change) >= 1.5:
            return StructureType.PULLBACK
        if "kol_attention" in candidate.tags:
            return StructureType.SENTIMENT
        return StructureType.UNKNOWN

    @staticmethod
    def _estimate_rr(candidate: Candidate) -> float:
        snapshot = candidate.snapshot
        base = 1.4
        if snapshot.quote_volume_24h > 100_000_000:
            base += 0.4
        if snapshot.funding_rate is not None and abs(snapshot.funding_rate) < 0.0005:
            base += 0.3
        if snapshot.btc_trend in {"up", "flat"}:
            base += 0.3
        if snapshot.relative_strength_score >= 0.6:
            base += 0.3
        if snapshot.follow_through_score >= 0.55:
            base += 0.2
        if snapshot.market_regime == "range_or_chop":
            base -= 0.5
        if snapshot.reversal_stage == "late_reversal":
            base -= 0.3
        return round(min(base, 4.0), 2)

    @staticmethod
    def _estimate_confidence(candidate: Candidate) -> float:
        snapshot = candidate.snapshot
        confidence = 0.35 + candidate.hard_score / 180
        if snapshot.market_regime in {"trend_or_acceleration", "uptrend_pullback"}:
            confidence += 0.04
        if snapshot.market_regime == "range_or_chop":
            confidence -= 0.10
        if snapshot.relative_strength_score >= 0.6:
            confidence += 0.04
        if snapshot.follow_through_score >= 0.55:
            confidence += 0.03
        if snapshot.reversal_stage == "late_reversal":
            confidence -= 0.08
        return round(max(0.05, min(confidence, 0.95)), 3)

    @staticmethod
    def _stop_pct(candidate: Candidate, structure: StructureType) -> float:
        snapshot = candidate.snapshot
        stop_pct = 0.025 if structure == StructureType.BREAKOUT else 0.018
        if snapshot.follow_through_score >= 0.6:
            stop_pct -= 0.003
        if snapshot.market_regime == "transition":
            stop_pct += 0.002
        return round(max(stop_pct, 0.012), 4)

    @staticmethod
    def _management_plan(candidate: Candidate, structure: StructureType) -> list[str]:
        snapshot = candidate.snapshot
        plan = [
            "do not widen the initial stop once the trade is live",
            "reduce risk only after the market proves acceptance beyond the trigger zone",
        ]
        if snapshot.reversal_stage == "first_reversal":
            plan.append("treat this as a first-reversal attempt; avoid low-quality re-entry if chop appears")
        if snapshot.reversal_stage == "late_reversal":
            plan.append("late reversal context: cut quickly if the move stalls after entry")
        if snapshot.retest_quality_score >= 0.6:
            plan.append("good retest context: trail under the accepted retest once continuation confirms")
        if structure in {StructureType.BREAKOUT, StructureType.MOMENTUM}:
            plan.append("if expansion fails to continue soon after entry, exit instead of hoping for delayed follow-through")
        if snapshot.relative_strength_score >= 0.6:
            plan.append("keep sizing focus on leaders; rotate out if relative strength deteriorates")
        return plan
