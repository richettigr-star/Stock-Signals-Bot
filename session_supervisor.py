"""Carry GitHub supervision across sessions without relying on a daily cron start."""
import argparse
import os
import time
from datetime import timedelta

import requests

from action_runtime import GitStore, dispatch
from common import NY, load_json, now_utc, save_json, session_bounds
from monitor_watchdog import assess, heartbeat_time
from notifications import send

HEALTH_FILE = "supervisor_health.json"
WORKFLOWS = ("intraday-exits.yml", "monitor-watchdog.yml")
RECOVERY_COOLDOWN = 900


def supervised_window(now):
    bounds = session_bounds(now.astimezone(NY).date())
    return bool(bounds and bounds[0] - timedelta(minutes=10) <= now <= bounds[1] + timedelta(minutes=20))


def workflow_runs(workflow):
    token = os.getenv("GH_TOKEN", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    if not token or repository != "richettigr-star/Stock-Signals-Bot" or workflow not in WORKFLOWS:
        raise RuntimeError("Supervisor destination or credentials unavailable")
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/runs",
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"},
            params={"branch": "main", "per_page": 100}, timeout=15)
        response.raise_for_status()
        runs = response.json()["workflow_runs"]
        if not isinstance(runs, list) or any(not isinstance(run, dict) or not run.get("status") for run in runs):
            raise ValueError("Invalid workflow response")
        return runs
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise RuntimeError("Workflow availability could not be verified") from None


def supervise_once(store, *, clock=now_utc, list_runs=workflow_runs, trigger=dispatch):
    now = clock()
    previous = load_json(HEALTH_FILE, {})
    health = {
        "checked_at_utc": now.isoformat(),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "origin_event": os.getenv("GITHUB_EVENT_NAME"),
        "status": "standby",
        "last_requests": previous.get("last_requests", {}),
        "last_alert_bucket": previous.get("last_alert_bucket"),
        "workflows": {},
        "problems": [],
    }
    if not supervised_window(now):
        save_json(HEALTH_FILE, health)
        store.checkpoint()
        return True

    problems = health["problems"]
    for workflow in WORKFLOWS:
        try:
            active = [run for run in list_runs(workflow) if run["status"] != "completed"]
            if active:
                health["workflows"][workflow] = {
                    "status": active[0]["status"], "run_id": active[0].get("id")}
                continue
            requested = heartbeat_time(health["last_requests"].get(workflow))
            if requested and 0 <= (now - requested).total_seconds() < RECOVERY_COOLDOWN:
                health["workflows"][workflow] = {"status": "awaiting_requested_runner"}
                problems.append(workflow + ": runner solicitado ainda não observado")
            elif trigger(workflow):
                health["last_requests"][workflow] = now.isoformat()
                health["workflows"][workflow] = {"status": "recovery_requested"}
                problems.append(workflow + ": recuperação solicitada; início não comprovado")
            else:
                health["workflows"][workflow] = {"status": "dispatch_failed"}
                problems.append(workflow + ": pedido de recuperação falhou")
        except (RuntimeError, ValueError, OSError):
            health["workflows"][workflow] = {"status": "unverified"}
            problems.append(workflow + ": disponibilidade não verificada")

    try:
        monitor = load_json("monitor_health.json", {})
        portfolio = load_json("portfolio_state.json", required=True)
        phase, reading_problems = assess(now, monitor, portfolio)
        problems.extend(reading_problems)
        health["monitor_assessment"] = phase
    except (RuntimeError, ValueError, OSError):
        problems.append("estado do monitor ou das posições ilegível")

    bounds = session_bounds(now.astimezone(NY).date())
    alert_window = now >= bounds[0] + timedelta(minutes=12)
    try:
        watchdog = load_json("watchdog_health.json", {})
        checked = heartbeat_time(watchdog.get("checked_at_utc"))
        watchdog_fresh = bool(checked and 0 <= (now - checked).total_seconds() <= 180)
    except (ValueError, OSError):
        watchdog_fresh = False
    if alert_window and not watchdog_fresh:
        problems.append("watchdog sem supervisão recente comprovada")
        bucket = f"{now.astimezone(NY):%Y%m%d-%H}-{now.astimezone(NY).minute // 30}"
        if health["last_alert_bucket"] != bucket:
            event = {"id": "SUPERVISOR-" + bucket, "type": "MONITOR_HEALTH",
                     "component": "session supervisor", "created_at_utc": now.isoformat(),
                     "detail": "Supervisão intraday indisponível: " + "; ".join(problems),
                     "telegram_alert_status": "pending"}
            health["notifications_ok"] = send(event)
            if health["notifications_ok"]:
                health["last_alert_bucket"] = bucket
            else:
                problems.append("alerta do supervisor não entregue ao Telegram")

    health["status"] = "degraded" if problems else "ok" if alert_window else "opening_grace"
    save_json(HEALTH_FILE, health)
    store.checkpoint()
    return not problems


def run_supervisor(duration=330 * 60, *, clock=now_utc, monotonic=time.monotonic,
                   sleep=time.sleep, store=None, cycle=None, handover=dispatch):
    store = store or GitStore((HEALTH_FILE,))
    cycle = cycle or (lambda current_store: supervise_once(current_store, clock=clock))
    deadline = monotonic() + duration
    next_tick = monotonic()
    handed_over = False
    last_ok = False
    try:
        while monotonic() < deadline:
            if deadline - monotonic() <= 600 and not handed_over:
                handed_over = handover("session-supervisor.yml")
            if monotonic() < next_tick:
                sleep(min(60, next_tick - monotonic(), deadline - monotonic()))
                continue
            if store.sync():
                return 0 if handover("session-supervisor.yml") else 1
            last_ok = bool(cycle(store))
            interval = 60 if supervised_window(clock()) else 300
            next_tick += interval
            if next_tick <= monotonic():
                next_tick += (int((monotonic() - next_tick) // interval) + 1) * interval
        if not handed_over:
            handed_over = handover("session-supervisor.yml")
        health = load_json(HEALTH_FILE, {})
        health["handover_requested"] = handed_over
        health["handover_requested_at_utc"] = clock().isoformat()
        save_json(HEALTH_FILE, health)
        store.checkpoint()
        return 0 if last_ok and handed_over else 1
    except Exception as exc:
        print("Supervisor stopped safely: " + type(exc).__name__, flush=True)
        if not handed_over:
            handover("session-supervisor.yml")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-seconds", type=int, default=330 * 60)
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= 330 * 60:
        parser.error("duration must be between 1 and 19800 seconds")
    raise SystemExit(run_supervisor(args.duration_seconds))
