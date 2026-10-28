# Donchian 4H 40/20 + EMA200 — v1 — FROZEN

Status: FROZEN / validated research benchmark
Frozen on: 2026-10-28
Scope: multi-pair USD-M Futures trend-following strategy, LONG + SHORT

## Frozen universe

Do not silently add or remove pairs. The validated universe is exactly:
- BTCUSDT
- ETHUSDT
- SOLUSDT
- XRPUSDT
- BNBUSDT
- DOGEUSDT
- ADAUSDT
- LINKUSDT

XRP was negative and BNB approximately flat in the 2025–Sep 2026 pair breakdown, but they remain in the frozen universe because removing them after seeing the test would be post-hoc retuning.

## Frozen signal logic

Signal timeframe: 4H.
Indicators are calculated from completed 4H candles only.

LONG signal:
1. 4H close > highest high of the prior 40 completed 4H bars.
2. 4H close > EMA200 (4H).

SHORT signal:
1. 4H close < lowest low of the prior 40 completed 4H bars.
2. 4H close < EMA200 (4H).

Execution:
- Signal is confirmed only at the 4H close.
- Entry is at the next 4H candle open.
- Maximum one open position per symbol for this strategy.

## Frozen exit logic

Initial protective stop:
- LONG: entry - 2.0 × ATR14 (4H).
- SHORT: entry + 2.0 × ATR14 (4H).

Channel exit:
- LONG: exit at the close when the 4H close falls below the lowest low of the prior 20 completed 4H bars.
- SHORT: exit at the close when the 4H close rises above the highest high of the prior 20 completed 4H bars.

Time exit:
- Maximum 60 completed 4H bars after entry (240 hours / 10 days).

Backtest ordering is conservative when applicable: protective stop is checked before the channel/time close exit. Historical stop modeling fills at the stop level and therefore does not separately model extreme gap-through-stop slippage.

## Costs and funding used for validation

- Base round-trip cost assumption: 0.12%.
- Stress round-trip cost assumption: 0.24%.
- Historical Binance USD-M funding payments are included while positions are open.
- Benchmark portfolio accounting used 10% of realized portfolio equity per trade at 1x for research comparison. Concurrent positions were allowed and the benchmark is not a finalized live risk engine.

## Validation design

The rule was selected using 2021–2023 only.
2024 was validation.
2025–Sep 2026 was locked test.
After the exact rule was selected, it was tested unchanged on an independent 2020 pre-sample holdout using all pairs for which Binance USD-M history was available during that year.

No 2024–2026 or 2020 result was used to change the 40/20 channel lengths, EMA200 filter, stop, exit, direction, or universe.

## Validation snapshot

### Independent 2020 holdout
- Trades: 213
- Win rate: 31.92%
- Profit factor: 1.389
- Benchmark return: +37.00%
- Max realized-equity drawdown: -14.23%
- Frequency: 4.07 trades/week
- Average hold: 121.58 hours
- Stress 0.24%: PF 1.349, return +33.55%
- Removing the three best trades: PF 1.124, return +10.66%

Note: several altcoin USD-M contracts launched during 2020, so their 2020 histories are partial. BTC and ETH have full 2020 coverage; all available histories were used without changing the universe rule.

### Development 2021–2023
- Trades: 840
- Win rate: 28.93%
- Profit factor: 1.297
- Benchmark return: +223.75%
- Max realized-equity drawdown: -35.09%
- Frequency: 5.37 trades/week
- Average hold: 113.22 hours

### Validation 2024
- Trades: 305
- Win rate: 31.48%
- Profit factor: 1.263
- Benchmark return: +24.38%
- Max realized-equity drawdown: -16.97%
- Frequency: 5.83 trades/week

### Locked test 2025–Sep 2026
- Trades: 505
- Win rate: 32.87%
- Profit factor: 1.194
- Benchmark return: +26.73%
- Max realized-equity drawdown: -19.73%
- Frequency: 5.54 trades/week
- Average hold: 115.80 hours
- Stress 0.24%: PF 1.140, return +19.28%
- Removing the three best trades: PF 1.093, return +12.13%

Calendar-year PF for the selected frozen rule:
- 2021: 1.455
- 2022: 1.011
- 2023: 1.434
- 2024: 1.263
- 2025: 1.093
- 2026 YTD through Sep: 1.336

All six calendar years 2021–2026 were positive in the benchmark. 2022 and 2025 were weak regimes and show that this is not a uniformly strong edge.

### Locked-test pair breakdown (2025–Sep 2026)
- BTCUSDT: PF 1.093
- ETHUSDT: PF 1.240
- SOLUSDT: PF 1.477
- XRPUSDT: PF 0.844
- BNBUSDT: PF 1.008
- DOGEUSDT: PF 1.421
- ADAUSDT: PF 1.319
- LINKUSDT: PF 1.120

Six of eight pairs were profitable in the locked test. Do not remove XRP or BNB based on this table without a new prospective validation design.

## Risk / implementation status

The strategy logic is frozen, but LIVE position sizing, leverage, portfolio exposure limits, liquidation modeling, and exchange-specific WEEX execution are NOT frozen or authorized by this document.

In the locked test, positions can overlap across the eight symbols. The research benchmark permits one position per symbol; therefore portfolio-level risk must be designed and re-simulated before live automation.

The low win rate (~30–33%) is expected for this trend-following family. The edge comes from winners being materially larger than losers, not from a high percentage of winning trades.

## Freeze rule

This file is the authoritative specification for Donchian 4H 40/20 + EMA200 v1. Do not retune channel lengths, EMA filter, stop, exit, directions, universe, or execution timing silently. Any future change must be a separately named candidate and must be compared against this frozen rule before promotion.
