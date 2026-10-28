# Donchian v2 ATR-buffer sensitivity — preregistration

Date: 2026-10-28
Parent experiment: `DONCHIAN_V2_REPO_INSPIRED_PREREG.md`
Frozen benchmark remains Donchian 4H 40/20 + EMA200 v1.

Round 1 identified the already-preregistered `ATRBUF_025` rule as the strongest eligible refinement. This round is a **robustness diagnostic, not a new optimizer**. The candidate threshold remains fixed at 0.25 ATR; no neighboring threshold will be promoted simply because it scores better on already-seen history.

## Fixed sensitivity grid

Same exact signal/execution/risk/cost/funding pipeline as v1, changing only the breakout clearance threshold:

- 0.00 ATR (baseline)
- 0.10 ATR
- 0.15 ATR
- 0.20 ATR
- 0.25 ATR (fixed candidate)
- 0.30 ATR
- 0.40 ATR
- 0.50 ATR
- 0.75 ATR

For long signals: `close > prior40_high + threshold * prior_ATR14`.
For short signals: symmetric below the prior40 low.

## Diagnostic interpretation fixed in advance

A robust plateau should show:
- no sharp performance cliff immediately adjacent to 0.25;
- most thresholds from 0.15 through 0.40 retaining PF > 1.0 in pre-2020, 2022, 2024, 2025 and 2025-Sep2026 aggregate;
- locked-comparison PF broadly at or above the v1 baseline across the neighborhood;
- trade count declining smoothly as the threshold rises rather than collapsing abruptly;
- stress-cost PF remaining > 1.10 around the candidate neighborhood.

This round also reports, without changing the rule:
- locked-test performance by pair and by side for baseline vs 0.25;
- exit-reason distribution;
- baseline-only vs candidate-only entry diagnostics, to understand what the buffer removes or makes possible.

No asset will be removed and no threshold will be retuned based on these results.
