#!/usr/bin/env python3
"""Detect a stale intraday monitor heartbeat and alert without mutating trading state."""
from datetime import timedelta
from common import NY, load_json, now_utc, parse_time, save_json, session_bounds, utc_now
from notifications import send

STALE_AFTER_SECONDS = 7 * 60
OPEN_GRACE_SECONDS = 12 * 60
POST_CLOSE_GRACE_SECONDS = 20 * 60


def heartbeat_time(value):
    try:
        return parse_time(value)
    except (ValueError, TypeError):
        return None


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
    completed = heartbeat_time(health.get("completed_at_utc"))
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
    elif health.get("status") != "ok":
        problems.append("monitor sem leitura efetiva")
    if health.get("notifications_ok") is not True:
        problems.append("entrega Telegram não confirmada")

    symbol_health = health.get("symbols", {})
    for symbol in symbols:
        item = symbol_health.get(symbol)
        if not item:
            problems.append(symbol + ": sem leitura recente")
        elif item.get("status") != "ok":
            problems.append(symbol + ": leitura " + str(item.get("status")))
        elif item.get("holding_confirmed") is False:
            problems.append(symbol + ": holding não confirmada pelo monitor")
        else:
            checked = heartbeat_time(item.get("checked_at_utc"))
            if checked is None or not 0 <= (now - checked).total_seconds() <= STALE_AFTER_SECONDS:
                problems.append(symbol + ": leitura atrasada ou ausente")

    return ("degraded" if problems else "ok"), problems


def main():
    now = now_utc()
    read_errors = []
    try:
        health = load_json("monitor_health.json", {})
    except (ValueError, OSError):
        health = {}
        read_errors.append("monitor health ilegível")
    try:
        portfolio = load_json("portfolio_state.json", required=True)
    except (ValueError, OSError, RuntimeError):
        portfolio = {}
        read_errors.append("portfolio ilegível; holdings não verificadas")
    try:
        previous = load_json("watchdog_health.json", {})
    except (ValueError, OSError):
        previous = {}
    status, problems = assess(now, health, portfolio)
    if read_errors and status in {"ok", "degraded", "no_active_holdings"}:
        problems.extend(read_errors)
        status = "degraded"
    watchdog = {
        "checked_at_utc": utc_now(),
        "status": status,
        "active_holdings": active_holdings(portfolio),
        "problems": problems,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "last_alert_bucket": previous.get("last_alert_bucket"),
        "last_recovery_requested_at_utc": previous.get("last_recovery_requested_at_utc"),
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
