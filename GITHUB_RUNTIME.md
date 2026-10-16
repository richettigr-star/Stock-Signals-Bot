# Intraday reliability: GitHub-only operation

## Decision and limits

The user requires GitHub-only infrastructure. An always-on server with independent supervision would improve startup reliability but is outside that constraint. An external cron that only dispatches Actions would still depend on runner allocation and would add infrastructure. Increasing cron frequency or putting two scans inside one ten-minute workflow does not solve missed triggers.

The chosen design runs the polling clock inside an allocated Actions runner. Recovery schedules bootstrap sessions; successors are requested by the running worker before the six-hour platform limit. A separate Actions runner supervises committed observations without waiting for the trading-state queue.

Official references checked on 2026-10-16:

- [Schedule events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): scheduled starts can be delayed or dropped under load; schedules only run on the default branch. Timezone-aware schedules are supported.
- [Actions limits](https://docs.github.com/en/actions/reference/limits): GitHub-hosted jobs have a six-hour execution limit.
- [Concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency): the default queue replaces pending runs; `queue: max` preserves up to 100 pending jobs/runs with `cancel-in-progress: false`.
- [Triggering workflows](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow): `workflow_dispatch` is an exception to the normal suppression of events generated with `GITHUB_TOKEN`.

Dispatch acceptance is not proof that its successor started. Neither the daily bootstrap nor runner replacement has a timing SLA. The watchdog is separate from the monitor process but shares GitHub's failure domain. This design must never be described as 100% available.

## Operation

1. `Intraday Exit Signals` starts from a manual dispatch, code push or recovery schedule.
2. The worker waits for 09:31 NY so a first regular minute bar can exist. Holidays, early closes and DST use the XNYS calendar.
3. Scans start on a monotonic 300-second clock. Slow work skips missed slots instead of bursting requests; failed data or Telegram delivery does not cancel later scans.
4. The latest `main` state is read before each scan. Runtime code/dependency changes cause a handover to a freshly installed worker.
5. EXIT outbox events are saved before removing their positions. Pending outbox and state are pushed before Telegram delivery. Receipts are saved after each attempted notification and pushed before another scan.
6. Health, dashboard and cadence evidence are checkpointed each cycle. Push failures retry; concurrent changes to owned state stop the worker rather than merging financial state blindly. Artifacts preserve local evidence and an unpushed outbox for manual reconciliation.
7. At 320 minutes a successor is requested; the current worker yields at 330 minutes. Operational jobs share `stock-signal-state` with `queue: max`; daily jobs cannot overwrite an active monitor. Some daily jobs scheduled intraday may wait and subsequently skip or process the now-completed session.
8. `Intraday Monitor Watchdog` starts on the monitor's requested event or its own recovery schedules/manual dispatch. It checks remote health every minute, uses its own queue, alerts after seven minutes without an effective check and requests a recovery monitor at most every 15 minutes. It has the same bounded budget and self-handover.
9. Both workers exit after exchange close plus 20 minutes. The next session still requires a successful bootstrap.

Runtime credentials remain the existing Actions secrets `TWELVE_DATA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Handover uses only the temporary repository token with Actions write permission, not a personal token. No credentials are in JSON evidence or artifacts. Runtime state pushes made with `GITHUB_TOKEN` do not recursively start normal push workflows.

Exactly-once Telegram delivery across a crash after API acceptance remains impossible without a transactional receiver. The durable event ID and sent receipt suppress normal reruns; a crash in that narrow acceptance/receipt interval can still duplicate an alert. A successful Telegram API response also does not prove device delivery.

## Preserved state

The implementation patch does not modify `signal_state.json`, `portfolio_state.json`, `signal_events.json`, existing health snapshots or prices. At the inspected base `90acec40bd62da13aa099aaef6e33b82ebd13501`:

- COST is the only confirmed holding, with stop 946.711.
- WMT and UNH are `pending_entry`, absent from confirmed holdings.
- Intraday processing does not lower or raise stops. Only the existing completed-daily-bar trailing rule may raise them; an actual crossing can still generate an EXIT.

## Rollout and acceptance

Publish the tested code/workflows together, preserving current remote JSON state. Start `Intraday Exit Signals` manually on `main` while the exchange is open; confirm its requested event starts the watchdog, or dispatch the watchdog manually. Do not disable the daily scanner or overwrite runtime state with an older local snapshot.

Required evidence:

- CI passes with installed dependencies, including real-calendar tests.
- At least three consecutive fresh, advancing COST observations span approximately ten minutes; intervals are at most 360 seconds. Check `python verify_cadence.py`, run IDs, committed timestamps and quote times. No API call means no effective sample, even if a job is green.
- Pending WMT/UNH remain skipped and COST stop remains 946.711 unless a dated legitimate daily trailing update raises it.
- Watchdog checks continue while the monitor holds its state queue. Telegram delivery failures, stale quotes and missed reads produce degraded status rather than success.
- Observe a runner handover and one complete unattended next-session start before claiming broader operational validation. A short mid-session test does not establish those properties.

The cadence checker reports only its recorded window. It rejects repeated quotes, stale data, missing/failed observations, gaps and an expired last observation. Its retained history is bounded to 200 samples, so it is not a permanent uptime audit. Artifacts expire after seven days.

## Validation status

Local offline tests passed during implementation. No real cadence, unattended bootstrap, Telegram delivery or runner handover is established by offline tests. Fill this section with actual GitHub run URLs and observation timestamps after rollout; do not replace missing evidence with an inferred PASS.
