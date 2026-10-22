# Isolated server runtime

The approved target is the existing crypto server, but stocks use a separate Unix
user, Python environment, data directory, systemd service and existing stock
Telegram identity. No exchange or broker order integration is installed.

## Preserved behavior

The original scanner, confirmed-holding filter, dated daily trailing stops and
Telegram event IDs remain authoritative. Do not reset state from an old checkout.
Only import the final GitHub snapshot after disabling **and stopping** all legacy
stock writers. Keep a dated backup of that snapshot, its commit and its outbox.

The monitor starts at 09:31 New York, then uses five-minute session-aligned slots.
XNYS handles holidays, daylight saving and shortened sessions. The process stays
resident between sessions; systemd restarts it after failures or a missed process
heartbeat. Each market-data subprocess is bounded to 240 seconds. The independent
minute watchdog checks actual monitor health and Telegram delivery, not merely a
successful service start. Daily scanning begins after the monitor's close-plus-20
minute grace window and retries failures every 15 minutes until local midnight.

Local JSON replacement is flushed to disk before sending notifications; each
accepted Telegram receipt is also saved immediately. Telegram has no idempotency
key: a connection loss after acceptance but before the local receipt can still
produce a duplicate retry. A single writer, preserved IDs and sent receipts avoid
ordinary duplicates but do not justify claiming exactly-once network delivery.

## Preparation and cutover

1. Install the reviewed release in `/opt/stock-signals`, then run
   `bash deploy/prepare-server.sh` as root. This does not start any service.
2. Generate a temporary RSA encryption key on the destination only. Verify its
   public fingerprint. Export only the three existing stock secrets to an encrypted,
   authenticated one-day Actions artifact. Never publish plaintext secrets or the
   private key. Import into root-only `/etc/stock-signals/telegram.env`.
3. Verify both Telegram identities with `getMe` without sending test alerts; they
   must be distinct. Do not change crypto's credentials, service or state.
4. Run `deploy/cutover_actions.py` with a short-lived GitHub Actions token. Confirm
   all stock workers have stopped. Import **all** current state/outbox/health files
   from the recorded commit into `/var/lib/stock-signals` owned by `stocksignals`.
5. Verify positions/stops against that snapshot, run offline tests on the server,
   then enable `stock-signals.service` and `stock-signals-watchdog.timer`.
6. Record three fresh, advancing observations across roughly ten minutes, with
   intervals at most 360 seconds. Validate watchdog, outbox, unchanged crypto and
   persisted state. Initial assisted deployment is not automatic-opening evidence.

## Operations and limits

Inspect `journalctl -u stock-signals`, `systemctl status stock-signals` and the
local health/cadence JSON files. Back up `/var/lib/stock-signals` and root-only
configuration privately. Code updates must never replace local state from Git.
The old GitHub JSON and public Pages dashboard stop being live after cutover;
do not present their old green status as server evidence. A dashboard mirror needs
an independently authorized, narrow access mechanism; none is provisioned here.

Rollback is deliberate: stop both stock server units, retain the latest local
state/outbox, and reconcile it before enabling any GitHub writer. Never simply
re-enable old workflows against stale GitHub positions. Both bots share one server
and therefore a host outage remains a shared failure domain. This is a signal
system, not a broker stop order, and cannot guarantee continuous availability.
