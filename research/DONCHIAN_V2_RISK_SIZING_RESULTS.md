# Donchian v2 — risk sizing / leverage research

Date: 2026-10-28
Status: RESEARCH ONLY. Donchian v1 remains frozen. Donchian v2 signal remains candidate/not live.

## Signal held fixed

All tests use `Donchian 4H 40/20 + EMA200 + 0.25 ATR breakout clearance` on the fixed eight-pair universe (BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK). Signal parameters were not retuned in this risk research.

Historical source through 2026-09-30: official Binance USD-M 1H monthly bars resampled to 4H, cost 0.12% round trip, historical funding included. Realized-equity DD is measured at exits and is not mark-to-market DD.

## 50% margin per entry rejected

With eight assets the historical source signal reached peak concurrency of eight positions. Allocating 50% account margin to each entry can finance only two simultaneous positions and therefore changes the strategy materially. In 2026 through Sep, only 72 of 190 source signals were accepted and 118 skipped. Results with 50% margin per entry were negative at every tested leverage (1x through 10x); 1x ended at $74.83 from $100 and 10x at $0.27.

## Exhaustive fixed-notional grid

3,780 combinations were tested across:
- margin/entry: 5, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 50%
- leverage: 1,2,3,4,5,6,7,8,10x
- max positions: 2,3,4,5,6,8
- gross caps: 100,150,200,250,300,400,500%

Key 2026 Jan-Sep fixed-notional frontier:

| Notional/position | Return | Realized DD | Notes |
|---:|---:|---:|---|
| 12.5% | +19.88% | -20.76% | low exposure |
| 15% | +21.36% | -24.83% | all signals |
| 17.5% | +23.99% | -28.36% | all signals |
| 20%, gross cap 150% | +26.56% | -30.59% | 4.74% signals skipped |
| 22.5%, gross cap 175% | +28.82% | -33.72% | 4.74% signals skipped |
| 25%, gross cap 200% | +33.53% | -37.42% | full-history DD ~-64%, rejected as operational default |

At 0.24% total cost, 20%-notional/cap150 returned +21.31%; at 0.36% cost it returned +16.27%. Priority randomization for simultaneous entries showed the 20%-cap150 configuration was not highly sensitive to alphabetical tie-break: YTD returns across priority permutations ranged roughly +24.95% to +26.84%.

Directional LONG/SHORT concentration caps were tested separately. Limiting same-direction positions did not improve the short-horizon frontier; the best YTD configurations retained side cap 8 / total cap 8 and used gross exposure to control portfolio size.

## Stop-risk sizing — superior architecture

Position notional was set from the fixed 2 ATR initial stop:

`notional = (equity * risk_budget) / (2*ATR / entry_price)`

The historical 2 ATR stop distance across 1,455 candidate trades had median ~4.50%, p10 ~2.53%, p90 ~8.07%, max ~27.13%.

5,184 combinations were tested across:
- risk/trade: 0.5%, 0.75%, 1%, 1.25%, 1.5%, 2%, 2.5%, 3%
- leverage: 2,3,4,5,7,10x
- portfolio heat: 4,6,8,10,12,16%
- gross cap: 100,150,200,250,300,400%
- max positions: 4,6,8

### Three useful tiers

| Tier | Risk/trade | Leverage choice* | Heat cap | Gross cap | 2026 Jan-Sep return | DD | 2025-Sep26 return | 2021-Sep26 return | Full DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Recommended / controlled | 0.50% | 3x | 4% | 250% | +30.29% | -22.36% | +68.61% | +822.84% | -26.06% |
| Aggressive | 0.75% | 3-4x | 6% | 300% | +41.53% | -31.67% | +101.26% | +2001.26% | -36.59% |
| Very aggressive | 1.00% | 4-5x+ | 8% | 400% | +49.91% | -39.93% | +129.72% | +4007.83% | -45.71% |

`*` Leverage does not create the target notional in stop-risk sizing; it only determines margin needed for the risk-sized notional. The lowest leverage that leaves reasonable margin headroom is preferable. For 0.50% risk, 3x historically used ~58.34% peak margin and ~175.01% peak gross, while maintaining large distance between the 2 ATR stop and approximate isolated liquidation. This is why 3x is the preferred leverage for the controlled tier.

2026 stress cost diagnostic for stop-risk sizing:

| Risk/trade | Return @0.12% | Return @0.24% | Return @0.36% | DD @0.12% | DD @0.36% |
|---:|---:|---:|---:|---:|---:|
| 0.50% | +30.29% | +25.82% | +21.50% | -22.36% | -24.52% |
| 0.75% | +41.53% | +34.37% | +27.56% | -31.67% | -34.52% |
| 1.00% | +49.91% | +39.94% | +30.62% | -39.93% | -43.24% |

2026 quarter behavior at base costs:

| Risk/trade | Q1 | Q2 | Q3 |
|---:|---:|---:|---:|
| 0.50% | +4.22% | +2.92% | +21.47% |
| 0.75% | +5.18% | +3.64% | +29.83% |
| 1.00% | +5.48% | +3.93% | +36.75% |

The large YTD result was therefore concentrated in Q3; this is another reason not to select the maximum risk tier solely on return.

## October 1-27 mini-forward

October had not been part of the historical optimization. Official Binance daily USD-M 1H price archives were appended through 2026-10-27 UTC. There were only 18 closed candidate trades; open trades at the cutoff were omitted. Binance daily funding files were unavailable at the tested archive path and the REST endpoint was geoblocked from the runner, so October forward uses price plus 0.12% assumed cost and **no October funding**. Historical 0.24% and 0.36% cost stresses provide a separate conservative friction check but are not a substitute for exact October funding.

October was hostile to the strategy:

| Risk/trade | October return | October DD | Closed signals executed |
|---:|---:|---:|---:|
| 0.50% | -7.01% | -7.01% | 18/18 |
| 0.75% | -10.37% | -10.37% | 18/18 |
| 1.00% | -13.63% | -13.63% | 18/18 |

Fixed-notional sizing showed the same monotonic pattern (12.5% notional -6.98%; 25% notional -13.59%). This is a small sample but a real forward warning: current October conditions do not support increasing exposure merely because Q3/backtest returns were strong.

October closed instrument-return sums were negative for 7/8 assets; ETH was the only positive pair in the closed sample. This supports the interpretation of a broad unfavorable trend-following regime rather than a single-pair anomaly.

## Current conclusion

For actual short-term forward use, the best-supported starting risk layer is **0.50% account risk per trade at the 2 ATR initial stop, 3x leverage, 4% aggregate initial-risk/heat cap, 250% gross-notional cap, max 8 positions**. This is not the historical maximum-return configuration, but it dominates fixed 15-20% notional sizing on historical return/DD and loses materially less in the October mini-forward.

The 0.75% tier is the aggressive candidate if the user explicitly accepts ~30% historical realized DD and larger current-regime losses. The 1% tier is not recommended for initial live deployment because the return increase is accompanied by ~40-46% historical realized DD and materially worse October forward losses.

Do not promote these results to live sizing until mark-to-market equity, exact venue margin/liquidation, gap/slippage and WEEX-specific fees/funding are modeled. Realized-exit DD understates possible intratrade risk.
