# Donchian 4H v2 — repo-inspired research results

Date: 2026-10-28
Status: **V2 CANDIDATE / NOT PROMOTED / NOT LIVE**
Frozen benchmark remains: `DONCHIAN_4H_40_20_EMA200_V1_FROZEN.md`

## What external GitHub research contributed

The most useful public repositories were:

- `EstebanSP23/crypto_systematic_research` — Donchian/Turtle-style crypto research, OOS methodology, robustness-first refinement, ATR risk concepts, and useful examples of refinements that failed future data.
- `Yibaii/algo-breakout` — causal Donchian implementation, shifted prior channel, ATR breakout clearance, volume filter, walk-forward structure.
- `peterskwang/sol-momentum-strategy` — BTC macro regime, relative-volume confirmation, ATR risk sizing and portfolio constraints for perpetual futures.
- `kaidenmerk/FreqTradeCryptoBot` — Monte Carlo bootstrap tooling and operational protections.
- `freqtrade/freqtrade` — lookahead analysis, recursive analysis, backtesting/hyperopt and drawdown/cooldown protections.
- `nautechsystems/nautilus_trader` — event-driven production-grade backtest/live architecture with fills, latency, margin and execution simulation; relevant for the next risk/execution phase rather than signal selection.

Pyramiding was intentionally excluded from the first refinement round because public research showed it can be unusually sensitive to overfitting and because the existing v1 already has material concurrency risk.

## Frozen-v1 baseline reproduction

Before judging any refinement, the comparison engine was forced to reproduce the frozen v1 using the exact original pipeline: official Binance USD-M 1H monthly klines -> 4H resampling, 20-day warmup, separate 2020 and 2021-Sep2026 indicator states, same funding and same execution assumptions.

Exact reproduction:

| Block | Trades | PF |
| --- | ---: | ---: |
| 2020 independent | 213 | 1.388702 |
| 2021-2023 development | 840 | 1.297116 |
| 2024 validation | 305 | 1.262628 |
| 2025-Sep2026 locked comparison | 505 | 1.193846 |

An earlier native-4H implementation was not accepted for primary comparison because its 2020 baseline did not reproduce the frozen benchmark. It was retained only as a secondary data-construction robustness check.

## Round 1 — preregistered external ideas

Variants were fixed before results were inspected: 0.25 ATR breakout buffer, 1.0x/1.5x relative-volume filters, ATR+volume, daily EMA200 slope, BTC daily EMA20/50 regime, and an adverse-funding gate.

The cleanest improvement was **ATRBUF_025**:

Long signal becomes:

`close > prior_40_high + 0.25 * prior_ATR14` AND `close > EMA200`

Short signal becomes the exact symmetric condition below the prior 40-bar low.

Everything else stays identical to v1.

### Exact-pipeline comparison

| Block | v1 PF | ATRBUF 0.25 PF | v1 return | ATRBUF return |
| --- | ---: | ---: | ---: | ---: |
| 2020 | 1.3887 | 1.3940 | +37.0% | — |
| 2021-2023 | 1.2971 | 1.4105 | +223.8% | +293.6% |
| 2024 | 1.2626 | 1.2920 | +24.38% | +24.06% |
| 2025-Sep2026 | 1.1938 | 1.2564 | +26.73% | +31.26% |

Locked comparison details:

- trades: 505 -> 449
- PF: 1.193846 -> 1.256361
- return: +26.73% -> +31.26%
- realized-equity DD: -19.73% -> -17.24%
- stress-cost PF at 0.24% RT: 1.139664 -> 1.198891
- remove-top-3 PF: 1.093189 -> 1.145370
- 2022 PF: 1.011301 -> 1.028842
- 2025 PF: 1.093325 -> 1.156435

The ATR+volume combination also passed but did not improve enough over the simpler ATR-only rule to justify extra complexity. Volume-only variants were weaker. Daily EMA slope and BTC macro filters removed too many trades or failed weak-regime criteria. The funding gate added no locked-test benefit.

## Sensitivity — candidate is not an isolated optimum

The 0.25 threshold remained fixed before this diagnostic. Neighboring thresholds were tested only to determine whether the effect is a broad plateau or a single tuned spike.

| ATR clearance | Test PF | Test return | Test DD | Stress PF | PF 2022 | PF 2025 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.00 | 1.194 | +26.73% | -19.73% | 1.140 | 1.011 | 1.093 |
| 0.15 | 1.206 | +26.06% | -17.01% | 1.150 | 1.007 | 1.065 |
| 0.20 | 1.238 | +29.61% | -16.58% | 1.181 | 1.013 | 1.097 |
| **0.25** | **1.256** | **+31.26%** | **-17.24%** | **1.199** | **1.029** | **1.156** |
| 0.30 | 1.348 | +40.91% | -15.13% | 1.286 | 0.997 | 1.217 |
| 0.40 | 1.310 | +33.64% | -13.47% | 1.250 | 0.963 | 1.141 |
| 0.50 | 1.311 | +31.53% | -12.75% | 1.251 | 0.976 | 1.122 |
| 0.75 | 1.323 | +26.29% | -10.46% | 1.264 | 1.076 | 1.024 |

The effect is broad, not a 0.25-only spike. We deliberately do **not** switch to 0.30/0.40/0.50 despite higher recent metrics because that would be post-hoc optimization and several of those thresholds fall below PF 1 in 2022. The preselected 0.25 remains the candidate.

## Mechanism diagnostics

Locked 2025-Sep2026 pair PF, v1 -> candidate:

- BTC: 1.093 -> 1.200
- ETH: 1.240 -> 1.263
- SOL: 1.477 -> 1.693
- XRP: 0.844 -> 0.926
- BNB: 1.008 -> 1.005
- DOGE: 1.421 -> 1.427
- ADA: 1.319 -> 1.375
- LINK: 1.120 -> 1.128

No pair was removed after seeing results.

By direction:

- LONG PF: 1.345 -> 1.373
- SHORT PF: 1.043 -> 1.121
- SHORT realized-equity DD: -15.18% -> -11.30%

Exit counts:

- stops: 277 -> 244
- channel exits: 130 -> 119
- time exits: 98 -> 86

Because each symbol can hold only one position, the candidate is not a strict subset of baseline trades. The locked-test entry-set diagnostic found:

- common entries: 355 trades, PF 1.274
- baseline-only entries: 150 trades, PF 1.031, mean net +0.087% per instrument trade
- candidate-only entries enabled later by freeing the symbol: 94 trades, PF 1.191, mean net +0.498%

This is consistent with the buffer refusing marginal breakouts and leaving the symbol available for later, stronger breakouts.

## Binance Spot domain replication

The same fixed signal rules were run on official Binance Spot 1H -> 4H price history, with no funding. Short signals are analytical price-path tests only; this does not claim executable Spot shorting.

| Block | Spot v1 PF | Spot 0.25 PF |
| --- | ---: | ---: |
| 2020 | 1.656 | 1.598 |
| 2021-2023 | 1.367 | 1.459 |
| 2024 | 1.363 | 1.311 |
| 2025-Sep2026 | 1.188 | 1.241 |

Recent Spot DD improved from -20.62% to -17.36%, stress PF from 1.133 to 1.184, and remove-top-3 PF from 1.087 to 1.131. The candidate was not superior in every block, but the overall effect generalized to a distinct market-data domain instead of existing only in USD-M perpetual bars.

## Half-year robustness

Using fixed, non-overlapping half-year windows on the exact USD-M pipeline:

- 14 windows total.
- Candidate PF exceeded baseline in 11/14 windows.
- Candidate PF > 1 in 10/14 windows, the same count as baseline.

The candidate does **not** eliminate trend-following regime dependence. Losing candidate windows still exist: 2022H2, 2023H1, 2024H1 and 2025H1. Its benefit is improved quality/risk distribution, not a promise of profit in every regime.

## Moving-block Monte Carlo

10,000 simulations per strategy, contiguous blocks of 10 historical trade returns, fixed seed, 2021-Sep2026, 10% current-equity benchmark sizing per trade.

| Diagnostic | v1 | ATRBUF 0.25 |
| --- | ---: | ---: |
| Observed trade sample | 1,650 | 1,455 |
| Median simulated final return | +416% | +540% |
| 5th percentile final return | +22.5% | +62.0% |
| Probability final return > 0 | 97.13% | 98.99% |
| Median max realized DD | -36.40% | -30.73% |
| 5th percentile max DD | -56.83% | -48.86% |
| Probability DD worse than -30% | 76.54% | 53.64% |

The signal candidate improves the bootstrap distribution, but the Monte Carlo also makes clear that the current 10%-per-trade research benchmark has substantial sequence risk. These DDs are realized-equity diagnostics and still omit intratrade MTM, exchange margin, liquidation and execution-gap mechanics.

## Current conclusion

`Donchian 4H 40/20 + EMA200 + 0.25 ATR breakout clearance` is a **strong v2 signal candidate**. It has survived:

- exact reproduction of the frozen-v1 pipeline;
- preregistered historical comparison;
- broad parameter sensitivity around the fixed threshold;
- native-4H secondary data-construction check;
- Binance Spot price-domain replication;
- fixed half-year regime analysis;
- moving-block Monte Carlo.

It is **not promoted over v1 and is not a live rule yet**. All historical periods have now been inspected, so there is no pristine future temporal holdout left. The clean next proof must be prospective forward/paper data and/or an independent execution venue/domain.

## Recommended next research phase

Stop adding entry indicators for now. The next expected-value improvement should come from the risk/execution layer:

1. ATR-based position sizing instead of fixed 10% notional-per-trade benchmark.
2. Aggregate portfolio heat / initial-risk cap across concurrent crypto positions.
3. Correlation-aware or cluster-aware exposure caps.
4. Mark-to-market equity and intratrade DD rather than exit-only equity.
5. Real exchange margin, liquidation, slippage/gap and funding mechanics.
6. Forward/paper comparison v1 vs v2 candidate without further retuning.
7. Only after that, evaluate pyramiding as an isolated experiment; do not mix it into the candidate now.
