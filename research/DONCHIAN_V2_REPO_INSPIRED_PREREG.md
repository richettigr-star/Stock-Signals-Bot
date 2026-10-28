# Donchian v2 repo-inspired experiments — preregistration

Date: 2026-10-28
Baseline: frozen `DONCHIAN_4H_40_20_EMA200_V1_FROZEN.md`

The frozen v1 is not modified. This document fixes the experimental variants and acceptance criteria before their results are inspected.

## External ideas being tested

1. **ATR breakout buffer** — inspired by `Yibaii/algo-breakout`: require the breakout close to clear the prior Donchian boundary by a fraction of prior ATR.
2. **Relative-volume confirmation** — used by `Yibaii/algo-breakout`, `peterskwang/sol-momentum-strategy`, and many Freqtrade breakout implementations.
3. **Higher-timeframe regime alignment** — inspired by `EstebanSP23/crypto_systematic_research` (rising daily EMA200) and `peterskwang/sol-momentum-strategy` (BTC daily EMA20/EMA50 macro regime).
4. **Adverse funding gate** — inspired by the cost-aware notes in `EstebanSP23/crypto_systematic_research`: skip a new long when the latest completed funding is very positive, and skip a new short when it is very negative.

Pyramiding is deliberately excluded from Round 1. Public research in `EstebanSP23/crypto_systematic_research` contains both a surviving Donchian pyramid and a separate pyramid refinement that collapsed out of sample; the repo explicitly flags pyramiding as unusually curve-fit-prone.

## Fixed variants

All variants keep the frozen v1 universe, 4H timeframe, 40-bar entry channel, 20-bar channel exit, EMA200 4H trend filter, 2 ATR initial stop, next-bar-open entry, 60-bar time exit, one position per symbol, funding accounting, and 0.12% / 0.24% cost assumptions unless the variant definition explicitly adds a filter.

- `BASE_V1` — exact frozen rule.
- `ATRBUF_025` — require close > prior 40-bar high + 0.25 * prior ATR for long; symmetric downside for short.
- `VOL_100` — require signal-bar volume >= 1.00 * prior 20-bar average volume.
- `VOL_150` — require signal-bar volume >= 1.50 * prior 20-bar average volume.
- `ATRBUF_025_VOL_100` — both ATR buffer and 1.00x volume filter.
- `DAILY_EMA200_SLOPE20` — in addition to v1, long only when the previous completed daily EMA200 is above its value 20 completed daily bars earlier; short only when below.
- `BTC_MACRO_20_50` — in addition to v1, all longs only when previous completed BTC daily EMA20 > EMA50; all shorts only when EMA20 < EMA50.
- `FUNDING_GATE_5BP` — skip a long if latest completed funding rate > +0.05%; skip a short if latest completed funding rate < -0.05%.

No variant may be altered after results are viewed in this round.

## Evaluation blocks

- Pre-sample: 2020-01-01 through 2020-12-31 (available contract history only).
- Development reference: 2021-01-01 through 2023-12-31.
- Validation: 2024-01-01 through 2024-12-31.
- Locked comparison: 2025-01-01 through 2026-09-30.

The underlying dates are known from v1 research, so this is not a pristine new-market holdout. However, the variant definitions above are fixed from external repository ideas before variant results on these blocks are inspected. Any promoted v2 would still require either prospective forward data or an additional market-domain replication before replacing v1.

## Acceptance criteria for a v2 candidate

A variant is **eligible for further validation**, not automatic promotion, only if all of the following hold:

1. Locked-comparison PF >= BASE_V1 PF and stress-cost PF >= 1.10.
2. Validation PF >= 1.15.
3. Pre-sample 2020 PF >= 1.10, with at least 70% of BASE_V1's available 2020 trade count unless the filter specifically requires a higher-timeframe warmup.
4. At least 70% of BASE_V1's 2021-Sep2026 trade count.
5. Remove-top-3 locked-comparison PF >= 1.05.
6. Calendar-year PF >= 1.0 in both 2022 and 2025 (the two known weak regimes for v1).
7. Locked-comparison realized-equity drawdown must not be worse than BASE_V1 by more than 10% relative.
8. No post-hoc asset deletion is allowed.

If no variant passes, v1 remains the preferred strategy and the result is recorded as a failed refinement round.
