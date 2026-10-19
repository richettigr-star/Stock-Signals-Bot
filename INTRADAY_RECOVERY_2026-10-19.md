# Intraday assisted recovery — 2026-10-19

## Classification

**Opening FAIL; assisted recovery observed-window PASS.** The 09:30 NY opening was not monitored automatically within the 09:42 opening grace. No monitor/watchdog run or fresh committed observation existed when checked at 09:43, 09:48 and 09:53 NY. Workflows were enabled. GitHub did not expose an internal reason for the missing schedule events.

The user explicitly authorized publication and assisted recovery. Commit [`3b34621`](https://github.com/richettigr-star/Stock-Signals-Bot/commit/3b3462129773c9d01bc705d9913c49944581f97c) introduced a separate continuous supervisor without changing trading logic, positions, stops or credentials. Its push-triggered start is not evidence of unattended opening.

## Observed evidence

- [CI run 39265886685](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/39265886685): all 115 tests and compilation passed.
- [Monitor run 39265886743](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/39265886743): fresh COST observations at 10:06:21, 10:11:21 and 10:16:21 NY; quote minutes 10:05, 10:10 and 10:15. Intervals 300.162 and 299.947 seconds; quote ages 80–81 seconds.
- [Watchdog run 39265893436](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/39265893436): eleven checks by 10:16:17 NY; the first stale check remains counted, recovery recorded at 10:07:17, current status ok with no problems.
- [Supervisor run 39265886662](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/39265886662): current status ok at 10:16:17 NY. It sees existing workers and does not create duplicate startup requests. A watchdog-requested monitor successor is pending; that is not an observed runner handover.
- Evidence is pinned to source commit `d395fc23f1e16ac5025a15dc3ee1893c771011fa`, with per-file blob IDs in `intraday_recovery_2026-10-19.json`.

## Preserved trading state

COST remains the only confirmed position; active stop remains **947.974 USD**, raised from 946.711 by the existing completed-daily-close trailing rule on 2026-10-16, effective 2026-10-19 09:30 NY. WMT and XOM remain pending/unconfirmed; UNH is not a confirmed holding. No EXIT or pending/failed trading notifications existed in the pinned snapshot. Real startup health alerts were accepted by Telegram; no test trade or artificial EXIT was sent. No orders were placed.

## Still unverified

The observed ten-minute window does not validate the missed opening, an overnight supervisor chain, an actual budget-expiry handover, the next unattended opening, device delivery or future five-minute availability. The continuous supervisor removes normal dependence on a fresh daily cron only while its GitHub runner chain survives. It consumes GitHub runner time and shares the platform's failure domain. Recovery schedules and accepted dispatch requests have no startup guarantee.
