# 24-Month Research Backtest — QBTS / IONQ / RGTI / MU

Period: 2024-10-18 through 2026-10-16
Data: Twelve Data daily OHLC, split-adjusted (same provider/adjustment style as production)

## New-symbol results

| Symbol | Closed trades | Win rate | Strategy return | Buy & hold | Max drawdown |
|---|---:|---:|---:|---:|---:|
| QBTS | 19 | 47.37% | 195.57% | 1021.9% | -78.39% |
| IONQ | 17 | 41.18% | 6.07% | 149.04% | -65.11% |
| RGTI | 16 | 37.5% | 452.07% | 1104.08% | -81.61% |
| MU | 20 | 35.0% | 122.57% | 686.43% | -50.31% |

## Portfolio comparison

| Portfolio | Final equity | Return | Max drawdown | Closed trades | Win rate |
|---|---:|---:|---:|---:|---:|
| Baseline 20 | C$85.61 | -14.39% | -40.12% | 84 | 35.71% |
| Baseline + QBTS/IONQ/RGTI/MU | C$249.17 | 149.17% | -42.25% | 82 | 45.12% |

## Important assumptions

- Signal after completed daily close; entry at next regular-session open.
- Stop starts at signal close minus 2.5×ATR14 and only moves upward after completed daily bars.
- If a session opens below the stop, the backtest exits at the open rather than pretending a fill at the higher stop.
- No commissions, slippage, spread, tax, CAD/USD conversion, or Wealthsimple FX costs.
- This research branch does not modify the production universe or LIVE signals.
