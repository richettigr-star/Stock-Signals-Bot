# Stock server migration — observed recovery window

**Result: migrated; recent observed window PASS. Not 100% availability.**

The approved existing server now runs stocks under its own user, Python
environment, persistent state, systemd service and independent minute watchdog.
Stock and crypto Telegram identities were verified distinct with `getMe`; private
credential files cannot be read by the other bot's Unix user. No broker order
integration, public port or persistent GitHub write token was added.

## State and ownership

- Exact frozen GitHub source: `e11e14aac65761ce2def353a537d9d5654aeb562`.
- COST remains the only confirmed holding; stop **USD 959.1617**, unchanged by
  migration. CVX and WMT remain pending; UNH/XOM were not presumed bought.
- Legacy GitHub stock executors were disabled and their real jobs stopped before
  state import. The first cutover script failed closed because completed export
  jobs still had running workflow metadata. A separate API audit confirmed no
  queued or active stock writer; that failure is not rewritten as success.
- GitHub is now code/tests/history, not the authoritative live state. The public
  dashboard includes a migration warning. Live state is `/var/lib/stock-signals`.

## Effective reads, not merely active services

On 22 October 2026, New York was UTC−4:

| Completed NY | Provider minute bar NY | Quote age | Effective |
|---|---|---:|---|
| 13:21:05 | 13:19 | 122 s | yes |
| 13:26:06 | 13:24 | 123 s | yes |
| 13:31:07 | 13:29 | 124 s | yes |

Intervals were **301.144 s and 301.180 s**; span **602.324 s**. Quotes advanced;
no interval exceeded 360 seconds. At 13:31:53 NY, the recent three-reading
assessment was `observed_window_pass`, watchdog was OK, supervisor was recent,
the outbox had no pending/failed events and six local state backups existed.

Crypto stayed active with the same process, PID 63360, and zero restarts. Stocks
recovered automatically after a deliberate stock-only process termination. Both
stock service and watchdog timer were enabled for boot; a real host reboot was
not performed because it would interrupt crypto.

## Incidents retained, not hidden

Initial stock startup found restrictive root-created code-directory permissions.
The fix allows the stock user to read public code and includes a service-user
preflight; private state/configuration remain restricted. Four initial failed
starts and the one deliberate recovery account for the stock restart counter of 5.

At 13:16, the provider returned a quote aged **185 seconds**, correctly classified
as degraded, not fresh. A real operational alert was accepted by the stock Telegram
bot (message 28). The server now retries stale provider snapshots at most twice,
15 seconds apart, **without increasing the 180-second freshness threshold**.
Watchdog recovered at 13:22 and retains five failed checks plus one recovery.
The full day's cadence history still includes the failed read; only the separately
labelled recent window passes. No test alert, fake ENTRY/EXIT or stop change was
created to demonstrate delivery.

## Tests and remaining limits

[Final GitHub verification](https://github.com/richettigr-star/Stock-Signals-Bot/actions/runs/39822632417)
passed **131 offline tests and compileall**; the same 131 tests passed on the server.
Coverage includes calendar slots/DST/holidays/early closes, frozen-state safety,
encrypted credential envelopes, durable receipts, backups and stale-data retries.

This is an **assisted deployment and a recovered intraday window**, not proof of
the next unattended opening, first after-close server scan or whole-host recovery.
Both bots share a host; local backups do not protect against loss of that host.
No availability guarantee or broker-level stop protection is implied.

Machine-readable evidence: [server_cutover_2026-10-22.json](server_cutover_2026-10-22.json).
