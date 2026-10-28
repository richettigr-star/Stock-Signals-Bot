# Donchian v2 ATRBUF 0.25 — final robustness diagnostics preregistration

Date: 2026-10-28
Candidate remains fixed: Donchian 4H 40/20 + EMA200 + 0.25 prior-ATR breakout clearance.
Benchmark remains frozen v1 with zero buffer.

No parameter is selected or altered in this round.

## Test A — fixed half-year windows

Using the exact Binance USD-M 1H -> 4H frozen-v1 pipeline, compare baseline and candidate on non-overlapping UTC half-year windows from 2020 through Sep-2026.

Diagnostics:
- PF, return, drawdown, trade count per half-year;
- count of windows with PF > 1;
- count of windows in which candidate PF exceeds baseline PF;
- check for any isolated half-year collapse.

There is no requirement that candidate beat baseline in every window. Supportive robustness means the improvement is distributed across multiple regimes rather than coming from one or two windows.

## Test B — moving-block bootstrap

Inspired by Monte Carlo tooling found in public Freqtrade research repositories, bootstrap chronological **net trade returns** from 2021 through Sep-2026 using contiguous moving blocks of 10 trades. This preserves some local serial dependence unlike IID shuffling.

- 10,000 simulations per strategy.
- Fixed seed: 20261028.
- Each simulation contains the same number of trades as that strategy's observed sample.
- Benchmark accounting: each trade changes realized equity by 10% of current realized equity times its net return, matching the research benchmark.
- Report final-return median, 5th/95th percentiles, median max realized-equity DD, 5th percentile max DD, probability of positive final return, and probability max DD is worse than -20% and -30%.

This Monte Carlo remains a realized-equity diagnostic and does not solve intratrade mark-to-market or margin/liquidation modeling. Those belong to the later portfolio/execution engine step.
