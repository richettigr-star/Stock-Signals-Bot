# GitHub-only intraday validation — 2026-10-16

Implementation: [50a9adbbcd430b3ea04948cbcd0a438287f3c6c8](https://github.com/richettigr-star/Stock-Signals-Bot/commit/50a9adbbcd430b3ea04948cbcd0a438287f3c6c8).

## Tests

- [GitHub CI](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/38936467896): 84 tests passed on Python 3.12; compilation passed. All operational regression suites also passed before entering the live monitor and watchdog loops.
- Local suite: 84 tests passed with installed dependencies, including the real XNYS calendar tests for holidays, early close and DST.
- Simulated full worker budget: 66 scans exactly 300 seconds apart over 330 minutes; successor requested at second 19200, 600 seconds before expiry. This is a clock simulation, not a live runner handover.

## Live observations

[Monitor run 38936467819](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/38936467819) started from the implementation push and continued polling inside one allocated runner. These observations are committed in [monitor_cadence.json](https://github.com/richettigr-star/Stock-Signals-Bot/blob/main/monitor_cadence.json).

All times below are New York/Toronto EDT on 2026-10-16.

| Effective check completed | Provider COST minute bar | Quote age | Interval since previous check |
|---|---|---:|---:|
| 13:02:07.541 | 13:00 | 127 seconds | First observation |
| 13:07:07.681 | 13:05 | 127 seconds | 300.140 seconds |
| 13:12:07.538 | 13:10 | 127 seconds | 299.857 seconds |

**PASS for the observed window:** three fresh advancing observations over 599.997 seconds, no failed or repeated readings, no interval above 360 seconds. The actual cadence checker returned `observed_window_pass`. The retained [validation snapshot](intraday_validation_2026-10-16.json) contains the timestamps, assessment, health, watchdog and position summaries supporting this result.

The first observed COST price was US$990.01; the third was US$990.91. COST remained the only confirmed holding with stop 946.711. WMT and UNH remained pending and were listed as skipped in monitor health. No broker order was placed, no EXIT was recorded, and no notifications were pending at validation.

[Watchdog run 38936471315](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/38936471315) ran simultaneously using its separate queue. At 13:01:46 it correctly detected the old 11:15 heartbeat, sent a Telegram health alert accepted at 13:01:47 and requested monitor recovery at 13:01:48. Subsequent committed checks at 13:03, 13:06 and 13:08 were `ok`, with no problems and Telegram delivery healthy. The startup warning described the pre-existing outage, not a fabricated EXIT.

## Scope and remaining evidence

The implementation uses in-run polling, checkpointed outbox/state/receipts, bounded processes, non-cancelling state serialization, independent watchdog checks and explicit successor dispatches. It does not rely on a fresh schedule event for each five-minute reading.

Unverified: a full unattended session start, live budget-expiry handover, platform-outage recovery and delivery to the user's physical device. No artificial real-position EXIT was generated for testing. Telegram failure and deduplication tests use offline fixtures.

GitHub documents that [scheduled starts can be delayed or dropped](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). Both workers still depend on GitHub availability. This report establishes only its recorded observation window; it does not certify 100% operation or future uptime.
