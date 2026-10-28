# Donchian v2 — MTM + WEEX execution/liquidation validation

Date: 2026-10-28
Status: RESEARCH ONLY. Donchian v2 signal remains frozen as a candidate, not live.

## Scope

The signal layer was not changed: 4H Donchian 40/20 + EMA200 + 0.25 ATR breakout clearance, universe BTC/ETH/SOL/XRP/BNB/DOGE/ADA/LINK, initial stop 2 ATR, frozen channel/time exits.

This test replaces realized-exit-only equity with hourly mark-to-market equity and adds:
- current public WEEX API taker fee per pair;
- current public WEEX first-tier maintenance margin ratio per pair;
- isolated and conservative cross-margin liquidation diagnostics;
- 0 / 2 / 5 / 10 bps slippage per side;
- stop gap-through logic at the worse 1H open;
- historical Binance USD-M funding retained as a historical funding proxy;
- MTM drawdown at hourly close and a conservative intrahour adverse-extreme drawdown.

Historical prices remain Binance USD-M trade-price data, not historical WEEX mark-price data. Therefore liquidation modeling is a stress proxy, not a venue-perfect historical reconstruction.

## WEEX public parameters captured on 2026-10-28

First-tier MMR returned by the public riskLimits endpoint:

| Pair | MMR |
|---|---:|
| BTCUSDT | 0.15% |
| ETHUSDT | 0.15% |
| SOLUSDT | 0.20% |
| XRPUSDT | 0.20% |
| BNBUSDT | 0.25% |
| DOGEUSDT | 0.25% |
| ADAUSDT | 0.20% |
| LINKUSDT | 0.25% |

The public exchangeInfo endpoint returned API taker fee = 0.08% per side for all eight pairs.

A separate MMR stress scenario forced 1.00% MMR for every pair.

## Trade population

1,455 frozen signal templates from 2021-01-01 through 2026-09-30.
2 ATR initial-stop distance: median 4.5043%, p90 8.0721%, maximum 27.1324%.

## Main result — current WEEX MMR, isolated margin

### Full 2021–Sep 2026

| Tier | Risk/trade | Leverage | Slippage/side | Return | MTM close DD | Adverse MTM DD | Liquidations | Peak gross | Peak margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Controlled | 0.50% | 3x | 0 bps | +862.96% | -29.31% | -29.60% | 0 | 182.63% | 62.04% |
| Controlled | 0.50% | 3x | 5 bps | +679.87% | -29.78% | -30.06% | 0 | 177.40% | 60.24% |
| Controlled | 0.50% | 3x | 10 bps | +535.72% | -30.23% | -30.51% | 0 | 172.51% | 58.56% |
| Aggressive | 0.75% | 4x | 0 bps | +2160.55% | -40.61% | -40.98% | 1 | 270.31% | 68.86% |
| Aggressive | 0.75% | 4x | 5 bps | +1561.29% | -41.20% | -41.57% | 1 | 262.69% | 66.90% |
| Very aggressive | 1.00% | 5x | 0 bps | +4442.83% | -50.17% | -50.59% | 1 | 355.73% | 72.49% |
| Very aggressive | 1.00% | 5x | 5 bps | +2941.38% | -50.85% | -51.25% | 1 | 345.85% | 70.46% |

The controlled tier had zero isolated liquidations under both live MMR and forced 1% MMR, at every tested slippage level. The aggressive and very-aggressive tiers each produced one isolated liquidation over the full history.

## YTD 2026 — current WEEX MMR, isolated margin

| Tier | Slippage/side | Return | MTM close DD | Adverse MTM DD | Liquidations | Peak gross | Peak margin |
|---|---:|---:|---:|---:|---:|---:|---:|
| Controlled 0.50% / 3x | 0 bps | +29.25% | -28.54% | -28.60% | 0 | 177.82% | 57.76% |
| Controlled 0.50% / 3x | 2 bps | +27.49% | -28.77% | -28.82% | 0 | 175.94% | 57.15% |
| Controlled 0.50% / 3x | 5 bps | +24.93% | -29.09% | -29.14% | 0 | 173.20% | 56.28% |
| Controlled 0.50% / 3x | 10 bps | +20.90% | -29.62% | -29.67% | 0 | 168.83% | 54.88% |
| Aggressive 0.75% / 4x | 0 bps | +40.12% | -39.29% | -39.35% | 0 | 265.42% | 64.67% |
| Aggressive 0.75% / 4x | 5 bps | +33.39% | -40.00% | -40.06% | 0 | 258.62% | 63.04% |
| Very aggressive 1.00% / 5x | 0 bps | +48.10% | -48.34% | -48.41% | 0 | 352.18% | 68.67% |
| Very aggressive 1.00% / 5x | 5 bps | +38.95% | -49.15% | -49.23% | 0 | 343.29% | 66.96% |

## Recent 2025–Sep 2026

Controlled 0.50% / 3x:
- 0 bps: +62.22%, adverse MTM DD -28.60%, zero liquidations.
- 5 bps: +51.06%, adverse MTM DD -29.14%, zero liquidations.
- 10 bps: +41.01%, adverse MTM DD -29.67%, zero liquidations.

## MMR stress result

For controlled 0.50% / 3x, forcing MMR = 1.00% for every pair produced the same return/DD and zero liquidations at all slippage levels. This indicates the 2 ATR stop/risk sizing historically exits far enough ahead of the modeled liquidation boundary for the controlled tier.

Aggressive and very-aggressive isolated tiers retained one historical liquidation under the 1% MMR stress.

## Cross-margin diagnostic

Controlled tier produced the same results in isolated and cross modes, with no liquidations.

Cross margin avoided the single isolated liquidation seen in the two higher-risk tiers, but drawdowns remained approximately 41–52%. Cross collateral therefore does not justify increasing initial risk: it transfers single-position liquidation risk to shared account collateral.

## What changed versus the prior realized-equity test

The previous controlled 2026 realized-exit DD was about -22.36%. Hourly MTM shows approximately -28.60% at zero slippage and -29.14% at 5 bps/side. The realized-only model therefore understated the actual open-position drawdown by roughly 6–7 percentage points.

The previous return and the new return are not perfectly apples-to-apples because the new engine charges current WEEX taker fees explicitly, sizes from current MTM equity, and replays stops on 1H bars. The MTM test should be used primarily for risk/liquidation validation, not as a replacement return benchmark.

## Gap result

No 1H-open gap-through-stop events were observed in the tested historical sample. This does not prove zero execution gap risk at sub-hour/tick level; it only means no gap-through was visible at the 1H resolution used here.

## Current decision

The controlled layer remains the only tier suitable for further forward consideration:

- 0.50% account risk per trade at the 2 ATR stop
- 3x leverage
- 4% portfolio heat cap
- 250% gross-notional cap
- maximum 8 positions

However, operational risk expectation should now use approximately **30% historical MTM drawdown**, not the earlier 22% realized-equity figure.

The 0.75% / 4x and 1.00% / 5x tiers are rejected for initial live use because they show ~41% and ~51% MTM drawdowns and each experienced one modeled isolated liquidation over the full historical sample.

October 1–27 forward remains a separate warning: the 0.50% tier lost about 7.01% over the 18 closed forward trades previously tested. Passing the historical MTM/liquidation test does not erase that recent unfavorable regime.

## Limitations

- Historical price source is Binance USD-M, not WEEX historical mark price.
- Historical funding is Binance funding, not WEEX historical funding.
- Current 2026-10-28 WEEX MMR/fee schedule is applied as the venue-risk configuration; historical WEEX tier changes are not reconstructed.
- Intrahour adverse MTM combines each active long's hourly low and short's hourly high, which is conservative and can overstate simultaneous portfolio loss because extremes need not occur at the same minute.
- Slippage is deterministic (0/2/5/10 bps per side), not order-book replay.
- No tick-level gap or latency model.
