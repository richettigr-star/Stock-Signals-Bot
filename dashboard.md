# Stock Signals — Dashboard

Snapshot UTC: 2026-10-16T20:07:08.440552+00:00

**Monitor as of this snapshot: ok**
Last check UTC: 2026-10-16T20:07:07.564630+00:00.
During the session, a last check older than 10 minutes means monitoring is unavailable, even if this saved snapshot says OK.
Telegram: **configured** · Undelivered events: 0.
Daily scan: ok · Last processed bar: 2026-10-15.

Initial capital: C$ 100.00 · Invested cost: C$ 33.33 · Unallocated cash: C$ 66.67
Realized P&L: C$ 0.00 · Closed trades: 0 · Wins: 0 · Losses: 0

| Holding | Status | Entry USD | Last observed USD | Strategy stop USD | USD return since entry | Quote NY (status) |
|---|---|---:|---:|---:|---:|---|
| COST | active | 985.40 | 989.1900 | 946.7110 | +0.38% | 2026-10-16 15:59:00 (ok) |

EXIT is an alert, not a broker sale. Cash and realized P&L change only after confirmed execution.
USD price return is not exact CAD P&L; share quantity, FX and fees are not yet recorded.
This chat is not continuously updating. Reload this GitHub page for the latest saved snapshot.

## Strategy signals without confirmed purchases

- UNH: pending_entry; strategy stop USD 377.4134. No real holding confirmed.
- WMT: pending_entry; strategy stop USD 111.5489. No real holding confirmed.

## Recent alerts

- ENTRY UNH: 2026-10-15T23:33:41.532260+00:00 · delivery sent · ID ENTRY-UNH-2026-10-15.
- ENTRY WMT: 2026-10-15T23:33:41.532260+00:00 · delivery sent · ID ENTRY-WMT-2026-10-15.
- STOP_UPDATE WMT: 2026-10-15T20:35:06.747285+00:00 · delivery sent · ID STOP_UPDATE-WMT-2026-10-15.
- ENTRY WMT: 2026-10-14T23:44:37.049099+00:00 · delivery skipped_stale · ID ENTRY-WMT-2026-10-14.
- ENTRY XOM: 2026-10-14T22:05:00+00:00 · delivery skipped_stale · ID ENTRY-XOM-2026-10-14.
- ENTRY COST: 2026-10-14T22:05:00+00:00 · delivery skipped_stale · ID ENTRY-COST-2026-10-14.

## Operational limits

Polling target: 5 minutes inside an allocated GitHub session runner. Startup, handover and upstream data can fail or be delayed; inspect monitor_cadence.json for effective readings.
Holidays and early closes use the XNYS calendar. Stops only rise from completed daily bars.
Entry execution time is unknown for legacy fills; first-day monitoring assumes session open unless a precise execution timestamp is recorded.
Corporate actions, trading halts and missing provider trades require reconciliation; a notification system is not a broker stop order.
