# Second Manual ETH Strategy Research — 2026-10-27

Goal: develop a strategy independent from the frozen ETH Squeeze Quality v3 — BTC Regime, optimized for higher entry confidence rather than breakout asymmetry.

Primary families:
1. Trend pullback / retest.
2. Trend-aligned mean reversion.

Research constraints:
- ETHUSDT only for first pass.
- Futures data first where available.
- Prefer 1H context with 15m/30m trigger or 1H-only rules that can be executed manually.
- No lookahead: signal at bar close, entry next bar open.
- Base round-trip trading cost: 0.12%; stress: 0.24%.
- Funding included where available in futures-domain tests.
- Target higher win rate than the frozen breakout strategy; desired >= 50% if achievable without destroying PF/frequency.
- Target useful frequency: roughly >= 1 trade/week, preferably 2–5/week.
- Average holding time target: < 24h.
- Require positive aggregate expectancy, PF > 1, reasonable year-to-year stability, and no dependence on a few best trades.
- Reject variants that look strong only after heavy parameter filtering.

The frozen ETH Squeeze Quality v3 remains untouched and serves only as a benchmark/diversifier.
