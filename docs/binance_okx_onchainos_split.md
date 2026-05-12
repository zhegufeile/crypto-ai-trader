# Binance + OKX OnchainOS Data Split

## Goal

Use Binance as the primary market engine and OKX OnchainOS as the on-chain signal booster.

This keeps the framework simple:

- Binance decides whether a setup is structurally tradable
- OKX OnchainOS helps decide whether capital flow is confirming the idea

## Binance Responsibilities

Binance stays in charge of:

- futures and spot market prices
- 24h change and quote volume
- open interest
- funding rate
- taker buy/sell ratio
- long/short ratio
- BTC background trend
- regime and follow-through inference

In short:

- Binance = price structure + derivatives context + execution quality

## OKX OnchainOS Responsibilities

OKX OnchainOS should boost or downgrade candidates using:

- smart money buy signals
- KOL / influencer signals
- whale participation
- wallet count confirmation
- sold ratio / still-holding context
- buy amount size
- later, token risk / holder concentration / cluster analysis

In short:

- OnchainOS = who is buying, how many are buying, and whether they are still holding

## Decision Order

1. Binance finds liquid tradable futures candidates
2. Binance computes regime, follow-through, retest quality, and relative strength
3. OnchainOS adds flow confirmation
4. Risk manager still has veto power

This means:

- no amount of on-chain hype should rescue a structurally bad Binance setup
- but a good Binance setup can be upgraded when smart money and KOL flow agree

## Candidate Selection Rule

### Strongest setups

- clean Binance trend or pullback
- strong relative strength
- good follow-through
- OnchainOS signal score above threshold
- multiple wallets or meaningful buy size

### Avoid

- late chop on Binance
- weak relative strength
- weak follow-through
- high sold ratio from tracked wallets

## Current Integration In Code

The current project now supports:

- optional `OKXClient`
- optional on-chain signal snapshot file
- candidate-level fields:
  - `onchain_signal_score`
  - `onchain_wallet_count`
  - `onchain_buy_amount_usd`
  - `onchain_sold_ratio_percent`
  - `onchain_wallet_types`

The booster adds score when:

- signal score is high
- multiple wallets confirm
- buy amount is meaningful
- sold ratio is low

The booster removes score when:

- tracked wallets already sold too much of the move

## Recommended Next Steps

1. Add a small exporter that converts real OnchainOS `signal list` results into the local snapshot JSON format
2. Add token-risk downgrade from OnchainOS advanced token info
3. Add sector and narrative clustering across Binance + OnchainOS
