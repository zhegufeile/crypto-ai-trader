# Strategy Cards

策略卡用于把 KOL / 复盘观点沉淀成可执行条件，而不是只看 24h 涨跌颜色。

## 方案 2：确认优先，减少追高

当前默认优先两类结构：

1. `htf_trend_pullback_reclaim`
   - 适用环境：`uptrend_pullback`
   - 核心条件：
     - `htf_trend_bias` 偏多
     - `retest_quality_score` 达标
     - `relative_strength_score` 达标
     - `distance_from_vwap_atr` 不宜过大
   - 目的：优先做强势币回踩后的再收复，避免只因 24h 收红就追突破。

2. `breakout_retest_confirmation`
   - 适用环境：`trend_or_acceleration`
   - 核心条件：
     - `breakout_acceptance_score` 达标
     - `relative_volume_ratio` 放大
     - `distance_from_breakout_level_atr` 靠近突破位
     - `follow_through_score` 仍健康
   - 目的：只做“突破后被市场接受”的二次确认，不做远离突破位的延伸追价。

## 过滤器

对 `breakout` / `momentum` 结构，新增以下否决条件：

- `breakout_acceptance_score` 太低
- `relative_volume_ratio` 不足
- `distance_from_vwap_atr` 过大
- `distance_from_breakout_level_atr` 过大
- `htf_trend_bias` 与交易方向冲突

## 示例

```json
[
  {
    "name": "htf_trend_pullback_reclaim",
    "market": "bullish",
    "entry_conditions": [
      "htf_trend_bias>=0.25",
      "market_regime=uptrend_pullback",
      "retest_quality_score>=0.65",
      "relative_strength_score>=0.65",
      "distance_from_vwap_atr<=0.75"
    ],
    "exit_conditions": [
      "reclaim_fails",
      "htf_bias_deteriorates",
      "follow_through_breaks"
    ],
    "risk_notes": [
      "avoid weak HTF trend",
      "avoid reclaim far above VWAP"
    ]
  },
  {
    "name": "breakout_retest_confirmation",
    "market": "trend_or_acceleration",
    "entry_conditions": [
      "breakout_acceptance_score>=0.65",
      "relative_volume_ratio>=1.35",
      "distance_from_breakout_level_atr<=0.35",
      "follow_through_score>=0.60"
    ],
    "exit_conditions": [
      "acceptance_lost",
      "retest_breaks_down",
      "relative_volume_fades"
    ],
    "risk_notes": [
      "avoid low-acceptance breakouts",
      "avoid entries already extended from breakout level"
    ]
  }
]
```
