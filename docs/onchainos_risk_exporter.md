# OnchainOS Risk Exporter

## Goal

Convert raw OKX OnchainOS risk outputs into a local risk snapshot used by candidate filtering.

This is the layer that should block:

- honeypot / cannot-sell style tokens
- critical token-scan risk
- extremely low liquidity
- extreme holder concentration
- abnormal dev / bundle / suspicious holding structure

## Important Rule

If your goal is to filter `貔貅盘`, you must prioritize:

- `onchainos security token-scan`

`token advanced-info` is useful, but by itself it is not enough to guarantee honeypot detection.

## Inputs

The exporter supports combining:

- raw `security token-scan` JSON
- raw `token advanced-info` JSON

You can provide one or both.

## Command

```powershell
.\.venv\Scripts\python.exe scripts\export_onchainos_risks.py --security-input data\onchainos\token_scan.raw.json --advanced-input data\onchainos\advanced_info.raw.json --output data\onchainos\risks.snapshot.json --chain solana
```

## Direct Refresh From OnchainOS CLI

If you already have `data/onchainos/signals.snapshot.json` with `token_address` and `chain`, you can refresh the risk snapshot directly:

```powershell
.\.venv\Scripts\python.exe scripts\refresh_onchainos_risks.py
```

This will:

1. Read tracked token addresses from `signals.snapshot.json`
2. Call `onchainos security token-scan`
3. Call `onchainos token advanced-info`
4. Save:
   - `data/onchainos/token_scan.raw.json`
   - `data/onchainos/advanced_info.raw.json`
   - `data/onchainos/risks.snapshot.json`

If your local machine cannot access OKX OnchainOS, run the same command on the Tencent Cloud server after deployment.

## Output

The exporter writes a normalized risk snapshot:

```json
{
  "source": "okx_onchainos",
  "kind": "risk_snapshot",
  "risks": [
    {
      "symbol": "SCAM",
      "risk_level": "CRITICAL",
      "risk_tags": ["honeypot", "lowLiquidity"],
      "honeypot": true,
      "is_safe_buy": false
    }
  ]
}
```

## Environment Configuration

Set this in `.env`:

```text
ONCHAIN_RISK_SNAPSHOT_FILE=data/onchainos/risks.snapshot.json
```

## How The Project Uses It

`MarketCollector` now applies these rules:

- honeypot or `is_safe_buy = false` -> hard penalty to zero
- `risk_level = CRITICAL` -> hard penalty to zero
- low on-chain liquidity -> heavy downgrade
- excessive top-10 concentration -> downgrade
- excessive dev / bundle / suspicious holding -> downgrade

`RiskManager` also blocks when:

- `onchain_honeypot = true`
- `onchain_is_safe_buy = false`
- `onchain_risk_level = CRITICAL`
- on-chain liquidity is too low

## Recommended Workflow

1. Export raw token-scan JSON
2. Export raw advanced-info JSON
3. Run `scripts/export_onchainos_risks.py`
4. Run candidate scanning
5. Treat any hard-block result as non-tradable unless manually reviewed
