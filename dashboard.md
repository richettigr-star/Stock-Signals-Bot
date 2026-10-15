# Dashboard — Stock Signals

Snapshot reconciled on 2026-10-15 from user-confirmed transactions. No live brokerage or price connection.

| Account | CAD |
|---|---:|
| Initial capital | 100.00 |
| Invested at cost | 33.33 |
| Unallocated capital | 66.67 |
| Realized P&L | 0.00 |
| Unrealized P&L | Not available |

| Holding | Status | Entry date | Entry USD | Invested CAD | Strategy stop USD |
|---|---|---|---:|---:|---:|
| COST | ACTIVE — user-confirmed fill | 2026-10-15 | 985.40 | 33.33 | 943.3110 |

WMT and XOM are unexecuted strategy signals, not account holdings.

The strategy stop comes from signal close minus 2.5 × ATR14. The previous dashboard's 946.7110 value comes from actual fill minus 2.5 × ATR14; it is a reference calculation only. No broker stop order is confirmed.

## Performance

- Today: unavailable without a current quote and previous close.
- Since entry: unavailable without a current quote; exact CAD P&L also requires quantity, FX and fees.
- Closed trades: 0. Winners: 0. Losers: 0. Win rate: not applicable.

## Operations

- Telegram: setup deferred by user.
- EXIT monitor: no run observed during reconciliation; operation not verified.
- Actual holdings: portfolio_state.json.
- Strategy signals and stops: signal_state.json.

This dashboard is a saved snapshot, not a continuously updating display. Future transactions and quotes must be reconciled before performance changes are reported.
