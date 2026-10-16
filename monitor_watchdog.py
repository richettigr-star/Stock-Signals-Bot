#!/usr/bin/env python3
"""Detect a stale intraday monitor heartbeat and alert through the existing Telegram outbox."""
from datetime import timedelta
from common import NY, append_event, load_json, now_utc, parse_time, save_json, session_bounds, utc_now
from notifications import deliver

STALE_AFTER_SECONDS = 12 * 60
OPEN_GRACE_SECONDS = 12 * 60
POST_CLOSE_GRACE_SECONDS = 20 * 60


def active_holdings(portfolio):
    return sorted(symbol for symbol, holding in portfolio.get("holdings", {}).items()
                  if holding.get("status") not in {"closed", "exit_alert_awaiting_manual_sale"})


def assess(now, health, portfolio):
    """Return (status, problems) without network calls; suitable for regression tests."""
    bounds = session_bounds(now.astimezone(NY).date())
    if not bounds:
        return "outside_session", []
    open_time, close_time = bounds
    if now < open_time + timedelta(seconds=OPEN_GRACE_SECONDS):
        return "opening_grace", []
    if now > close_time + timedelta(seconds=POST_CLOSE_GRACE_SECONDS):
        return "outside_session", []

    symbols = active_holdings(portfolio)
    if not symbols:
        return "no_active_holdings", []

    problems = []
    completed = parse_time(health.get("completed_at_utc"))
    if completed is None:
        problems.append("monitor heartbeat ausente")
    else:
        age = (now - completed).total_seconds()
        if age < 0:
            problems.append("monitor heartbeat no futuro")
        elif age > STALE_AFTER_SECONDS:
            problems.append(f"monitor atrasado {round(age / 60)} min")

    if health.get("status") in {"error", "degraded"}:
        problems.append("monitor status=" + str(health.get("status")))

    symbol_health = health.get("symbols", {})
    for symbol in symbols:
        item = symbol_health.get(symbol)
        if not item:
            problems.append(symbol + ": sem leitura recente")
        elif item.get("status") != "ok":
            problems.append(symbol + ": leitura " + str(item.get("status")))
        elif item.get("holding_confirmed") is False:
            problems.append(symbol + ": holding não confirmada pelo monitor")

    return ("degraded" if problems else "ok"), problems


def main():
    now = now_utc()
    health = load_json("monitor_health.json", {})
    portfolio = load_json("portfolio_state.json", required=True)
    events = load_json("signal_events.json", {"version": 1, "events": []})
    status, problems = assess(now, health, portfolio)
    watchdog = {
        "checked_at_utc": utc_now(),
        "status": status,
        "active_holdings": active_holdings(portfolio),
        "problems": problems,
        "stale_after_seconds": STALE_AFTER_SECONDS,
    }
    save_json("watchdog_health.json", watchdog)

    if problems:
        local = now.astimezone(NY)
        bucket = f"{local:%Y%m%d-%H}-{local.minute // 30}"
        append_event(events, {
            "id": "MONITOR-WATCHDOG-" + bucket,
            "type": "MONITOR_HEALTH",
            "component": "watchdog",
            "detail": "Proteção intraday degradada: " + "; ".join(problems),
            "created_at_utc": utc_now(),
            "telegram_alert_status": "pending",
        })

    save_json("signal_events.json", events)
    delivered = deliver(events)
    save_json("signal_events.json", events)
    watchdog["notifications_ok"] = delivered
    save_json("watchdog_health.json", watchdog)
    return 0 if not problems and delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
