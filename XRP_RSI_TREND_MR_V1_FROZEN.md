# XRP RSI Trend Mean Reversion v1 — FROZEN

Status: FROZEN / second manual-strategy benchmark
Frozen on: 2026-10-27
Scope: XRPUSDT long + short trend-aligned mean reversion

## Frozen entry logic

Signal timeframe: 1H.
Execution: signal confirmed on the 1H close; enter on the next 1H open.

Long:
1. RSI(14) < 30.
2. XRP close > EMA200 (1H).

Short:
1. RSI(14) > 70.
2. XRP close < EMA200 (1H).

No additional BTC filter, volume filter, 4H filter, funding filter, confirmation candle or retest is part of v1.

## Frozen exit logic

- Initial stop: 2.0 × ATR(14) from entry.
- No fixed take-profit.
- Long exits when RSI(14) reaches/crosses 50 (RSI >= 50).
- Short exits when RSI(14) reaches/crosses 50 (RSI <= 50).
- Maximum holding time: 24 hourly bars.
- Conservative backtest ordering: stop is checked before the RSI close-exit when both could occur in the same bar.

## Official Spot validation — Binance Spot, 2020–Sep 2026

Normalized portfolio sizing: 20% of realized equity per trade at 1x benchmark.
- Trades: 82
- Win rate: 64.63%
- Profit factor: 2.34
- Return: +22.77%
- Max realized-equity drawdown: -2.23%
- Average hold: 10.16 hours
- Stress cost 0.24%: PF 2.16, return +20.38%
- Long: 37 trades, PF 2.23
- Short: 45 trades, PF 2.46
- Positive years: 2020, 2021, 2023, 2024, 2025, 2026 YTD
- Negative year: 2022

## Independent Futures-domain replication — Binance USD-M, 2020-01-06 through 2026-09-30

The exact same rule above was copied without retuning. Historical funding timestamps were explicitly normalized and funding was applied to the holding interval.

Normalized portfolio sizing: 20% of realized equity per trade at 1x benchmark.
- Trades: 93
- Win rate: 62.37%
- Profit factor: 2.10
- Return: +23.97%
- Max realized-equity drawdown: -2.24%
- Expectancy on instrument return after modeled cost/funding: +1.17% per trade
- Average hold: 10.15 hours
- Frequency: 0.265 trades/week (roughly 1.15 trades/month)
- Maximum consecutive losses observed: 5
- Stress cost 0.24%: PF 1.94, return +21.24%
- Removing the three best trades: PF 1.69, return +14.05%
- Long: 39 trades, WR 64.10%, PF 2.28
- Short: 54 trades, WR 61.11%, PF 1.97
- Trades with non-zero funding: 70 / 93

Futures yearly behavior:
- 2020: PF 2.19, positive
- 2021: PF 3.14, positive
- 2022: PF 0.60, negative
- 2023: PF 1.37, positive
- 2024: PF 3.16, positive
- 2025: PF 2.20, positive
- 2026 through Sep: PF 2.57, positive

## Interpretation / use

This strategy is intentionally different from the frozen ETH Squeeze Quality v3. ETH v3 is a lower-win-rate breakout/trend strategy with roughly one trade per week; XRP RSI v1 is a higher-win-rate trend-aligned mean-reversion strategy with much lower signal frequency.

The strategy therefore complements the ETH strategy but does NOT solve the goal of generating several opportunities per week by itself.

## Sizing and leverage

No leverage level is frozen as part of this strategy. The validation benchmark is 20% realized equity allocation at 1x. Higher leverage simulations are not authorization to use leverage live; realized-equity drawdown understates intratrade mark-to-market risk and exchange-specific liquidation/slippage behavior is not fully modeled.

## Freeze rule

Do not retune RSI thresholds, EMA period, ATR stop, exit RSI, maximum holding time, symbol, or add filters silently. Any change must be researched as a separately named candidate/version and compared against this frozen v1 in independent data before promotion.
