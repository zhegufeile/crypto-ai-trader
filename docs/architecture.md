# Architecture

数据流：

```text
Binance/手动 KOL 数据
  -> MarketCollector
  -> Candidate
  -> Strategy rules + RuleBasedAnalyst/LLM
  -> RiskManager
  -> Simulator
  -> SQLite
  -> API/Notification
```

第一版把 AI 放在“解释与评分辅助”位置，最终能否交易由硬规则和风控决定。
