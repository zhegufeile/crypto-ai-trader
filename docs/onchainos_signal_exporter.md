# OnchainOS Signal Exporter

## Purpose

Convert raw OKX OnchainOS `signal list` JSON into the local snapshot format used by:

- `app.data.OKXClient`
- `app.data.MarketCollector`

This lets Binance remain the main market engine while OnchainOS boosts candidates with smart-money, KOL, and whale flow.

## Input

The exporter expects a JSON file saved from raw OnchainOS `signal list` output.

It supports these common shapes:

- top-level list
- `{ "signals": [...] }`
- `{ "data": [...] }`
- `{ "result": [...] }`
- nested `{ "data": { "items": [...] } }`

## Command

```powershell
.\.venv\Scripts\python.exe scripts/export_onchainos_signals.py data\onchainos\signal_list.raw.json --output data\onchainos\signals.snapshot.json --chain solana --min-signal-score 0.55 --min-wallet-count 2
```

## Output

The exporter writes a normalized snapshot JSON:

```json
{
  "source": "okx_onchainos",
  "kind": "signal_snapshot",
  "signals": [
    {
      "symbol": "PNKSTR",
      "token_symbol": "PNKSTR",
      "token_name": "Pink Star",
      "token_address": "so1111...",
      "chain": "solana",
      "chain_index": "501",
      "timestamp": "1710000000000",
      "signal_score": 0.78,
      "wallet_count": 5,
      "buy_amount_usd": 125000.0,
      "sold_ratio_percent": 18.0,
      "wallet_types": ["smart_money", "kol"]
    }
  ]
}
```

## Environment Configuration

Set these values in `.env`:

```text
ENABLE_ONCHAIN_SIGNAL_BOOST=true
ONCHAIN_SIGNAL_SNAPSHOT_FILE=data/onchainos/signals.snapshot.json
MIN_ONCHAIN_SIGNAL_SCORE=0.55
```

## Effect In Candidate Selection

Once configured, `MarketCollector` will:

- read Binance candidates first
- match base symbols against the OnchainOS snapshot
- add score when:
  - signal score is strong
  - multiple wallets confirm
  - buy amount is meaningful
  - sold ratio is still low
- subtract score when:
  - sold ratio shows wallets already exited too much

## Recommended Workflow

1. Export raw `onchainos signal list` JSON to `data/onchainos/signal_list.raw.json`
2. Run `scripts/export_onchainos_signals.py`
3. Run the scanner or scheduler as usual
4. Review whether Binance structure and OnchainOS flow are agreeing
