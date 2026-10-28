# Donchian v2 ATR-buffer — Binance Spot domain replication preregistration

Date: 2026-10-28
Candidate fixed before this test: `ATRBUF_025` from the repo-inspired futures experiment.
Benchmark: exact 40/20 + EMA200 v1 logic with zero ATR breakout buffer.

Purpose: test whether the 0.25 ATR breakout-quality filter generalizes to a different Binance market domain (Spot OHLCV) rather than only USD-M perpetual-futures bars.

This is a **signal-domain replication**, not a claim that short trades are executable on Spot. Both long and short signals are simulated symmetrically on Spot price history solely to test price-path robustness. Funding is absent. Base/stress round-trip costs remain 0.12% / 0.24%.

## Fixed design

Universe stays exactly BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, ADAUSDT, LINKUSDT where historical Binance Spot data exists.

Data: official Binance Vision Spot monthly 1H klines, resampled to 4H exactly as the futures benchmark.

Two independent indicator states are preserved:
- 2020 holdout with 20-day warmup;
- 2021 through Sep-2026 with 20-day warmup.

Rules other than the entry buffer are unchanged:
- prior 40-bar Donchian breakout;
- 4H EMA200 direction filter;
- next 4H open entry;
- 2 ATR14 initial stop;
- prior 20-bar Donchian exit;
- 60-bar maximum hold;
- one position per symbol.

## Interpretation fixed in advance

Supportive replication requires the 0.25 ATR candidate to:
1. improve or approximately preserve PF versus baseline in both 2024 and 2025-Sep2026;
2. remain PF > 1.0 on 2021-2023 aggregate and 2025-Sep2026 aggregate;
3. avoid a >20% relative worsening of locked-comparison drawdown;
4. retain at least 70% of baseline locked-comparison trades;
5. show no obvious collapse caused by a single pair.

No Spot result will be used to retune the 0.25 threshold.
