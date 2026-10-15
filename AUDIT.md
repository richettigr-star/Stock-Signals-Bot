# Reliability audit — 2026-10-15

This audit hardens the existing daily Momentum10 / EMA100 / Wilder ATR14 / 2.5×ATR, long-only strategy. It does not establish profitable performance or guarantee delivery.

## Corrected

| Issue | Correction |
|---|---|
| Manual daily runs could accept an unfinished daily candle | Exchange-session close plus a 15-minute allowance is required before processing today's daily bar |
| Weekdays were treated as trading days | XNYS exchange calendar covers holidays, early closes and daylight saving |
| ENTRY retries waited for the next daily job | One outbox is retried by the intraday monitor; entries expire at their intended next session open |
| EXIT and daily jobs used inconsistent retry policies | One Telegram sender validates HTTP and API ok, preserves failed alerts and labels delayed exits |
| Theoretical signals could request a real sale | EXIT and STOP_UPDATE messages explicitly identify whether a purchase is confirmed |
| New stops could be applied to older recovered bars | Stop history records its effective next-session open; old bars use their contemporaneous stop |
| Late daily jobs could raise stops before reconciling the old stop | Daily runner checks intraday history before processing the completed daily scan |
| Intraday monitor discarded yesterday's candles | A 1000-bar recovery window and persistent minute cursor cover approximately two sessions |
| Data failures could look successful | Invalid, stale, duplicate, future-only and missing data cause a degraded/error status; corrupted state is not silently reset |
| API keys could leak in error strings | Provider and Telegram exceptions are reduced to safe error types |
| Slot rounding could allocate a cent beyond available cash | Slot amounts are rounded down to cents and capped by unallocated confirmed-account cash |
| Dashboard balances and tickers were hardcoded | Account totals, holdings, signals, stops and delivery status are derived from JSON state |
| Rerunning old GitHub jobs could replay stale state | Operational workflows check out latest main and share one state lock |
| No regression CI | Offline test suite runs in CI and before operational jobs |

## Validation

The test suite covers indicator reference vectors, input validation, daily close gating, ranking, monotonic trailing stops, effective stop dates, cursor recovery, entry expiry, failed delivery, delayed exits, theoretical versus confirmed holdings, cash limits, corrupt state, and calendar integration. See the Signal Regression Tests workflow for the committed version's result.

## Operational limitations requiring follow-up

- GitHub cron is best effort: it can queue, delay or drop jobs. Changing the cron is not proof of a working five-minute schedule. Check actual event=schedule runs and heartbeat timestamps.
- A stopped scheduler cannot send its own outage alert. An independent heartbeat supervisor and an always-on host are required for stronger continuity.
- The current markdown dashboard is a saved snapshot. It cannot change its own status when no process runs. Compare its last-check timestamp with the current time.
- Provider minute bars may omit trades, arrive late, or be unavailable. This monitor is not a broker-native stop.
- Stock splits and other corporate actions are not automatically reconciled with stored stop levels or share quantities. Reconcile those before trading an affected holding.
- The legacy COST fill has no exact execution timestamp, quantity, FX or fees. Its first trading day assumes session-open monitoring; exact CAD P&L is unavailable.
- Telegram API acceptance does not prove that the user's device displayed or sounded the notification. Device mute, connectivity and notification settings remain outside this code.
- Cross-service exactly-once delivery is not guaranteed: a process can die between Telegram acceptance and persisted receipts. Event IDs make duplicates recognizable.
- Entries and exits are signals. Broker execution and its actual price must be confirmed separately.

## Source of truth

- signal_state.json: strategy signals, minute cursor, stop history.
- signal_events.json: alert outbox and Telegram delivery receipts.
- portfolio_state.json: user-confirmed holdings and account balances.
- monitor_health.json / daily_health.json: last execution health.
- dashboard.md: generated snapshot of those files.

Do not store tokens or private keys in repository files.
