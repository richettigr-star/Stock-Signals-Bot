#!/usr/bin/env python3
"""Detect a stale intraday monitor heartbeat and alert without mutating trading state."""
from datetime import timedelta
from common import NY, load_json, now_utc, parse_time, save_json, session_bounds, utc_now
from notifications import send

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
    if now < open_time:
        return "outside_session", []
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
    previous = load_json("watchdog_health.json", {})
    status, problems = assess(now, health, portfolio)
    watchdog = {
        "checked_at_utc": utc_now(),
        "status": status,
        "active_holdings": active_holdings(portfolio),
        "problems": problems,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "last_alert_bucket": previous.get("last_alert_bucket"),
    }

    delivered = True
    if problems:
        local = now.astimezone(NY)
        bucket = f"{local:%Y%m%d-%H}-{local.minute // 30}"
        if previous.get("last_alert_bucket") != bucket:
            event = {
                "id": "MONITOR-WATCHDOG-" + bucket,
                "type": "MONITOR_HEALTH",
                "component": "watchdog",
                "detail": "Proteção intraday degradada: " + "; ".join(problems),
                "created_at_utc": utc_now(),
                "telegram_alert_status": "pending",
            }
            delivered = send(event)
            if delivered:
                watchdog["last_alert_bucket"] = bucket
                watchdog["last_alert_sent_at_utc"] = event.get("telegram_alert_sent_at_utc")
            else:
                watchdog["last_alert_error"] = "Telegram delivery failed"

    watchdog["notifications_ok"] = delivered
    save_json("watchdog_health.json", watchdog)
    return 0 if not problems and delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
