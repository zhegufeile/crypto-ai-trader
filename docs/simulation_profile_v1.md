# Simulation Profile v1

This is the recommended parameter profile for the first long-running production simulation release.

## Target behavior

- Conservative enough to avoid noisy overtrading
- Flexible enough to allow `core+candidate` signals to work
- Strict enough to stop repeated bug-driven open/close loops quickly

## Recommended mode

- `USE_SIMULATION=true`
- `SIGNAL_STRATEGY_TIER_MODE=core+candidate`

If you want the most conservative mode for the first week, use:

- `SIGNAL_STRATEGY_TIER_MODE=core-only`

## Recommended core thresholds

```env
CONFIDENCE_THRESHOLD=0.72
MIN_RR=2.2
MIN_VOLUME_USDT=50000000
MIN_RELATIVE_STRENGTH_SCORE=0.60
MIN_FOLLOW_THROUGH_SCORE=0.48
MIN_RETEST_QUALITY_SCORE=0.55
```

## Recommended exposure controls

```env
MAX_POSITION_NOTIONAL_USDT=100
MAX_OPEN_POSITIONS=3
MAX_SAME_DIRECTION_POSITIONS=2
MAX_SAME_STRUCTURE_POSITIONS=2
```

## Recommended slowdown controls

```env
MAX_CONSECUTIVE_LOSSES=2
SYMBOL_COOLDOWN_MINUTES=90
PENDING_ENTRY_TIMEOUT_MINUTES=30
```

## Recommended safety breakers

```env
DAILY_MAX_LOSS_USDT=50
TRADE_ACTION_CIRCUIT_WINDOW_MINUTES=15
MAX_TRADE_ACTIONS_IN_WINDOW=6
MAX_TRADE_STATE_CHANGES_PER_SCAN=4
```

## Why this profile

1. It still allows good setups to pass
2. It sharply reduces repeated same-symbol churn
3. It limits correlation and same-style clustering
4. It contains abnormal loop risk before it becomes expensive

## Suggested rollout order

1. Start with `core-only` for the first smoke phase
2. Review journal events and blocked reasons
3. Move to `core+candidate` only after the loop/cooldown behavior looks healthy
