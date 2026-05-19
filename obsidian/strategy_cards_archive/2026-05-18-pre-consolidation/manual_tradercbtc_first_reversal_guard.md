# manual_tradercbtc_first_reversal_guard

- description: Trade only the first clean reversal or first high-quality reclaim after an extended move; avoid later chop and repeated retests after the easy move is gone.
- market: any
- timeframe: intraday
- creator: manual_review
- confidence_bias: 0.14
- preferred_symbols: none
- avoided_symbols: none
- preferred_market_states: trend_or_acceleration, uptrend_pullback
- entry_conditions: breakout, oi_rising, pullback_confirmation, first_reversal_only
- exit_conditions: stop_loss_hit, target_reached, support_lost, trailing_stop_hit
- invalidation_conditions: failed_follow_through_after_retest, range_expansion_without_direction, btc_turns_against_setup, funding_overheats
- risk_notes: do not take second or third reversal attempts once price is already chopping around the same zone, move stop only after the market proves acceptance beyond the reclaim or retest level, if the reclaimed level breaks back quickly, exit instead of widening risk
- historical_win_rate: unknown
- historical_rr: unknown
- sample_size: 1
- tags: execution, first-reversal, pullback, regime-filter
- source_posts: 1
