# Stock Signals — Dashboard

> **Automatic five-minute schedule: NOT WORKING in the observed test window.** At 11:14 Toronto, no scheduled runs appeared for 11:08 or 11:13. The last successful read at 11:04 was triggered by a push. See [verification evidence](SCHEDULE_VERIFICATION.md).

Snapshot UTC: 2026-10-15T15:04:43.279102+00:00

**Monitor as of this snapshot: ok**
Last check UTC: 2026-10-15T15:04:42.875316+00:00.
During the session, a last check older than 10 minutes means monitoring is unavailable, even if this saved snapshot says OK.
Telegram: **configured** · Undelivered events: 0.
Daily scan: unverified · Last processed bar: 2026-10-14.

Initial capital: C$ 100.00 · Invested cost: C$ 33.33 · Unallocated cash: C$ 66.67
Realized P&L: C$ 0.00 · Closed trades: 0 · Wins: 0 · Losses: 0

| Holding | Status | Entry USD | Last observed USD | Strategy stop USD | USD return since entry | Quote NY (status) |
|---|---|---:|---:|---:|---:|---|
| COST | active | 985.40 | 986.8550 | 943.3110 | +0.15% | 2026-10-15 11:03:00 (ok) |

EXIT is an alert, not a broker sale. Cash and realized P&L change only after confirmed execution.
USD price return is not exact CAD P&L; share quantity, FX and fees are not yet recorded.
This chat is not continuously updating. Reload this GitHub page for the latest saved snapshot.

## Strategy signals without confirmed purchases

- WMT: active; strategy stop USD 110.3869. No real holding confirmed.
- XOM: active; strategy stop USD 168.3714. No real holding confirmed.

## Recent alerts

- ENTRY XOM: 2026-10-14T22:05:00+00:00 · delivery skipped_stale · ID ENTRY-XOM-2026-10-14.
- ENTRY COST: 2026-10-14T22:05:00+00:00 · delivery skipped_stale · ID ENTRY-COST-2026-10-14.
- ENTRY WMT: 2026-10-14T23:44:37.049099+00:00 · delivery skipped_stale · ID ENTRY-WMT-2026-10-14.

## Operational limits

Polling target: 5 minutes during the regular exchange session. GitHub schedules and upstream data can be delayed.
Holidays and early closes use the XNYS calendar. Stops only rise from completed daily bars.
Entry execution time is unknown for legacy fills; first-day monitoring assumes session open unless a precise execution timestamp is recorded.
Corporate actions, trading halts and missing provider trades require reconciliation; a notification system is not a broker stop order.
