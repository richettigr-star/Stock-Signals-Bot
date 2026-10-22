"""Isolated, calendar-aware stock signal service; never submits broker orders."""
import fcntl
import os
import signal
import socket
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common import NY, load_json, monitor_window, now_utc, regular_bar, save_json, session_bounds, utc_now


def monitor_slot(now):
    bounds = session_bounds(now.astimezone(NY).date())
    if not bounds or not bounds[0] + timedelta(minutes=1) <= now <= bounds[1] + timedelta(minutes=20):
        return None
    return (now.astimezone(NY).date().isoformat(), int((now - bounds[0]).total_seconds() - 60) // 300)


def daily_due(now, health):
    day = now.astimezone(NY).date().isoformat()
    bounds = session_bounds(day)
    return bool(bounds and now > bounds[1] + timedelta(minutes=20)
                and not (health.get("bar_date") == day and health.get("scan_accepted")))


def notify(message):
    address = os.getenv("NOTIFY_SOCKET")
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.connect("\0" + address[1:] if address.startswith("@") else address)
            connection.sendall(message.encode())


def backup_state():
    directory = Path("backups")
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / (now_utc().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".tar.gz")
    with tarfile.open(str(target) + ".tmp", "w:gz") as archive:
        for name in ("signal_state.json", "portfolio_state.json", "signal_events.json", "monitor_health.json",
                     "monitor_cadence.json", "daily_health.json", "watchdog_health.json", "supervisor_health.json"):
            if Path(name).exists():
                archive.add(name, arcname=name)
    os.replace(str(target) + ".tmp", target)
    for old in sorted(directory.glob("*.tar.gz"))[:-200]:
        old.unlink()


def fresh_minute_bars(symbol, api_key, fetch):
    import intraday_exit
    for attempt in range(3):
        bars = fetch(symbol, api_key)
        now = now_utc()
        if not monitor_window(now):
            return bars
        latest = next((bar for bar in reversed(bars) if regular_bar(bar["datetime"])
                       and intraday_exit.bar_time(bar) <= now), None)
        bounds = session_bounds(now.astimezone(NY).date())
        age = (min(now, bounds[1]) - intraday_exit.bar_time(latest)).total_seconds() if latest else None
        if age is not None and 0 <= age <= 180:
            return bars
        if attempt < 2:
            time.sleep(15)
    return bars


def worker(kind):
    import build_dashboard
    import deliver_pending
    if kind == "monitor":
        import intraday_exit
        from verify_cadence import record_sample
        fetch = intraday_exit.fetch_today_minute_bars
        intraday_exit.fetch_today_minute_bars = lambda symbol, api_key: fresh_minute_bars(symbol, api_key, fetch)
        result = intraday_exit.run(defer_notifications=True)
        delivered = deliver_pending.main() == 0
        health = load_json("monitor_health.json", required=True)
        health.update(runtime="server", notifications_ok=delivered)
        if not delivered:
            health["status"] = "degraded"
        save_json("monitor_health.json", health)
        record_sample(health, result == 0 and delivered)
        build_dashboard.main()
        return int(result != 0 or not delivered)
    if kind == "daily":
        import daily_runner
        result = daily_runner.main()
        build_dashboard.main()
        return result
    return deliver_pending.main()


def run_child(kind, timeout, heartbeat):
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", kind],
                             start_new_session=True)
    started = time.monotonic()
    while child.poll() is None:
        heartbeat(kind)
        if time.monotonic() - started > timeout:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            if kind == "monitor":
                save_json("monitor_health.json", {"status": "error", "runtime": "server",
                          "completed_at_utc": utc_now(), "error": "worker_timeout"})
            return 124
        time.sleep(5)
    return child.returncode


def main():
    for name in ("signal_state.json", "portfolio_state.json", "signal_events.json"):
        load_json(name, required=True)
    lock = open("server-runtime.lock", "a", encoding="utf-8")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run_id = "server-" + uuid.uuid4().hex
    os.environ.update(GITHUB_RUN_ID=run_id, STOCK_DURABLE_OUTBOX="true")
    started = utc_now()

    def heartbeat(active=None):
        save_json("supervisor_health.json", {"runtime": "server", "run_id": run_id,
                  "status": "ok", "started_at_utc": started, "checked_at_utc": utc_now(),
                  "active_worker": active, "last_worker_result": last_result})
        notify("WATCHDOG=1")

    last_slot = None
    next_outbox = next_daily = 0
    last_result = None
    notify("READY=1")
    while True:
        now = now_utc()
        slot = monitor_slot(now)
        if slot is not None and slot != last_slot:
            last_slot = slot
            last_result = {"kind": "monitor", "code": run_child("monitor", 240, heartbeat),
                           "completed_at_utc": utc_now()}
            backup_state()
        elif slot is None and time.monotonic() >= next_daily and daily_due(
                now, load_json("daily_health.json", {})):
            last_result = {"kind": "daily", "code": run_child("daily", 1200, heartbeat),
                           "completed_at_utc": utc_now()}
            backup_state()
            next_daily = time.monotonic() + 900
        elif time.monotonic() >= next_outbox:
            last_result = {"kind": "outbox", "code": run_child("outbox", 180, heartbeat),
                           "completed_at_utc": utc_now()}
            next_outbox = time.monotonic() + 60
        heartbeat()
        time.sleep(5)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "worker":
        raise SystemExit(worker(sys.argv[2]))
    main()
