# ETH Squeeze Quality v3 — BTC Regime — FROZEN

Status: FROZEN / research benchmark
Frozen on: 2026-10-27
Scope: ETHUSDT long-only quality breakout research strategy

## Frozen entry logic

Signal timeframe: 1H.
Execution: signal confirmed on close; entry on next 1H open.

ETH conditions:
1. Recent squeeze condition from the existing v2 logic remains required.
2. ETH close > EMA100 (1H).
3. Volume > 1.20 × volume moving average used by v2.
4. ETH close > prior 20-bar high + 0.15 × ATR14.
5. Candle close-position quality >= 0.70 (close in top 30% of candle range).

BTC regime filter:
6. BTCUSDT 1H close > BTCUSDT EMA100 (1H) at the ETH signal close.

All six conditions are required. The BTC filter is the only structural change promoted from v2 to v3.

## Exit / management

Preserve the v2 exit and position-management logic unchanged. This freeze does not authorize retuning stops, trailing, sizing, leverage, take-profit, or execution timing.

## Validation snapshot

Primary futures study, 2020–Sep 2026, with real funding included and normalized 20% equity allocation at 1x:
- Trades: 371
- Win rate: 39.35%
- Profit factor: 1.59
- Return: +41.35%
- Max realized-equity drawdown: -4.31%
- Frequency: 1.05 trades/week
- Stress cost 0.24%: PF 1.40, return +29.32%
- Removing the three best trades: PF 1.41
- Positive calendar years: 7/7
- Maximum consecutive losses observed: 13

Independent Spot holdout 2018–2019:
- Trades: 86
- Win rate: 36.05%
- Profit factor: 1.37
- Return: +7.05%
- Max drawdown: -4.49%
- Stress PF: 1.24
- Stress return: +4.86%

## Rejected additions

Do not add these to the frozen v3 without a new explicit decision:
- ETH 4H EMA100 confirmation
- high-volatility-only filter
- funding filter
- extra combinations of those filters

Reason: they improved selected in-sample metrics but reduced frequency and/or robustness in the 2018–2019 holdout. In particular, BTC + ETH4H fell to roughly 0.51 trades/week in the holdout and became dependent on a small number of best trades.

## Freeze rule

This file is the authoritative frozen specification for this strategy. Do not retune or expand it silently. Any future change must be researched as a separately named candidate/version and compared against this frozen v3 benchmark before promotion.
