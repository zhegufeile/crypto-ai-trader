from app.ai.analyst import RuleBasedAnalyst
from app.data.schema import Candidate, Direction, MarketSnapshot, StructureType


def test_rule_based_analyst_outputs_trade_shape():
    candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="SOLUSDT",
            price=150,
            price_change_pct_24h=6,
            quote_volume_24h=150_000_000,
            funding_rate=0.0001,
            btc_trend="flat",
        ),
        hard_score=80,
    )

    result = RuleBasedAnalyst().analyze(candidate)

    assert result.symbol == "SOLUSDT"
    assert result.direction == Direction.LONG
    assert result.structure == StructureType.BREAKOUT
    assert result.take_profit and result.take_profit > result.entry
    assert result.management_plan


def test_rule_based_analyst_adds_management_for_first_reversal():
    candidate = Candidate(
        snapshot=MarketSnapshot(
            symbol="BTCUSDT",
            price=100,
            price_change_pct_24h=3.2,
            quote_volume_24h=200_000_000,
            funding_rate=0.0001,
            btc_trend="down",
            market_regime="trend_or_acceleration",
            reversal_stage="first_reversal",
            relative_strength_score=0.7,
            retest_quality_score=0.65,
            follow_through_score=0.62,
        ),
        hard_score=88,
    )

    result = RuleBasedAnalyst().analyze(candidate)

    assert any("first-reversal" in item for item in result.management_plan)
