"""Bounded GitHub session workers with durable checkpoints and explicit handover."""
import argparse
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import requests

from common import NY, load_json, now_utc, save_json, session_bounds, utc_now
from monitor_watchdog import heartbeat_time
from verify_cadence import record_sample

MONITOR_FILES = ("signal_state.json", "signal_events.json", "portfolio_state.json",
                 "dashboard.md", "monitor_health.json", "monitor_cadence.json")
WATCHDOG_FILES = ("watchdog_health.json",)
TERMINAL_ALERTS = {"sent", "skipped_stale", "skipped_superseded"}


class GitStore:
    def __init__(self, files):
        self.files = files

    def git(self, *arguments):
        result = subprocess.run(["git", *arguments], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError("Git checkpoint unavailable")
        return result.stdout.strip()

    def sync(self):
        self.git("fetch", "origin", "main")
        changes = self.git("diff", "--name-only", "HEAD", "origin/main").splitlines()
        self.git("merge", "--ff-only", "origin/main")
        return any(name.endswith(".py") or name == "requirements.txt" for name in changes)

    def checkpoint(self, files=None):
        owned = tuple(files or self.files)
        existing = [name for name in owned if Path(name).exists()]
        if existing:
            self.git("add", "--", *existing)
        if self.git("diff", "--cached", "--name-only"):
            self.git("commit", "-m", "Checkpoint " + os.getenv("GITHUB_RUN_ID", "session"))
        for attempt in range(3):
            try:
                self.git("push", "origin", "HEAD:main")
                return
            except RuntimeError:
                self.git("fetch", "origin", "main")
                base = self.git("merge-base", "HEAD", "origin/main")
                remote_changes = set(self.git("diff", "--name-only", base, "origin/main").splitlines())
                if remote_changes.intersection(self.files):
                    raise RuntimeError("Concurrent trading state change; checkpoint refused") from None
                self.git("rebase", "origin/main")
                if attempt < 2:
                    time.sleep(2)
        raise RuntimeError("Git checkpoint unavailable")


def dispatch(workflow):
    token = os.getenv("GH_TOKEN", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    if not token or repository != "richettigr-star/Stock-Signals-Bot":
        return False
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches"
    for attempt in range(3):
        try:
            response = requests.post(url, headers={"Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json"}, json={"ref": "main"}, timeout=15)
            if response.status_code == 204:
                return True
        except requests.RequestException:
            pass
        if attempt < 2:
            time.sleep(2)
    print("Handover dispatch failed; scheduled recovery remains best effort", flush=True)
    return False


def command(script, *arguments, timeout=150):
    try:
        return subprocess.run([sys.executable, script, *arguments], timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(script + ": bounded execution timed out", flush=True)
        return 1


def monitor_cycle(store):
    started = utc_now()
    result = command("intraday_exit.py", "--defer-notifications")
    health = load_json("monitor_health.json", {})
    if not health.get("started_at_utc") or health["started_at_utc"] < started:
        health = {"started_at_utc": started, "completed_at_utc": utc_now(),
                  "status": "error", "symbols": {}, "error": "scan_timeout_or_crash"}
    events = load_json("signal_events.json", {"events": []})
    pending = any(event.get("telegram_alert_status") not in TERMINAL_ALERTS
                  for event in events.get("events", []))
    if pending:
        store.checkpoint(("signal_state.json", "signal_events.json"))
    delivered = command("deliver_pending.py", timeout=100) == 0
    health["notifications_ok"] = delivered
    if not delivered:
        health["status"] = "degraded"
    health["run_id"] = os.getenv("GITHUB_RUN_ID")
    health["runtime"] = "github_session"
    save_json("monitor_health.json", health)
    record_sample(health, result == 0 and delivered)
    if command("build_dashboard.py", timeout=30):
        raise RuntimeError("Dashboard update failed")
    store.checkpoint()
    print("Checkpoint complete: " + str(health.get("status")), flush=True)
    return result == 0 and delivered


def watchdog_cycle(store):
    result = command("monitor_watchdog.py", timeout=100)
    try:
        health = load_json("monitor_health.json", {})
    except (ValueError, OSError):
        health = {}
    watchdog = load_json("watchdog_health.json", required=True)
    completed = heartbeat_time(health.get("completed_at_utc"))
    stale = completed is None or (now_utc() - completed).total_seconds() > 420
    previous_request = heartbeat_time(watchdog.get("last_recovery_requested_at_utc"))
    if watchdog.get("problems") and stale and (
        previous_request is None or (now_utc() - previous_request).total_seconds() >= 900
    ):
        if dispatch("intraday-exits.yml"):
            watchdog["last_recovery_requested_at_utc"] = utc_now()
            save_json("watchdog_health.json", watchdog)
    store.checkpoint()
    return result == 0


def run_session(mode, duration=330 * 60, *, clock=now_utc, monotonic=time.monotonic,
                sleep=time.sleep, cycle=None, store=None, handover=dispatch):
    now = clock()
    bounds = session_bounds(now.astimezone(NY).date())
    if not bounds or now < bounds[0] - timedelta(minutes=10) or now > bounds[1] + timedelta(minutes=20):
        print("Outside exchange session; no long worker started", flush=True)
        return 0
    store = store or GitStore(MONITOR_FILES if mode == "monitor" else WATCHDOG_FILES)
    cycle = cycle or (monitor_cycle if mode == "monitor" else watchdog_cycle)
    workflow = "intraday-exits.yml" if mode == "monitor" else "monitor-watchdog.yml"
    interval = 300 if mode == "monitor" else 60
    started = monotonic()
    deadline = started + duration
    next_tick = started
    handed_over = False
    had_failure = False
    try:
        while monotonic() < deadline and clock() <= bounds[1] + timedelta(minutes=20):
            if deadline - monotonic() <= 600 and not handed_over:
                handed_over = handover(workflow)
            first_reading = bounds[0] + timedelta(minutes=1)
            if clock() < first_reading:
                sleep(min(60, (first_reading - clock()).total_seconds(), deadline - monotonic()))
                next_tick = monotonic()
                continue
            if monotonic() < next_tick:
                sleep(min(60, next_tick - monotonic(), deadline - monotonic()))
                continue
            if store.sync():
                handover(workflow)
                print("Code changed; yielding to a fresh worker", flush=True)
                return 1
            had_failure = not cycle(store) or had_failure
            next_tick += interval
            if next_tick <= monotonic():
                next_tick += (int((monotonic() - next_tick) // interval) + 1) * interval
    except Exception as exc:
        print("Session stopped safely: " + type(exc).__name__, flush=True)
        if clock() < bounds[1] + timedelta(minutes=20):
            handover(workflow)
        return 1
    if clock() < bounds[1] + timedelta(minutes=20) and not handed_over:
        handed_over = handover(workflow)
        had_failure = not handed_over or had_failure
    return 1 if had_failure else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("monitor", "watchdog"))
    parser.add_argument("--duration-seconds", type=int, default=330 * 60)
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= 330 * 60:
        parser.error("duration must be between 1 and 19800 seconds")
    raise SystemExit(run_session(args.mode, args.duration_seconds))
