#!/usr/bin/env python3
"""Intraday EXIT signal monitor with emergency Telegram alerts.

Checks strategy signals remembered in signal_state.json. It does not place broker
orders. When a 1-minute bar trades at or below the stored stop, the signal is
closed in strategy state, an EXIT event is appended to signal_events.json, and
an emergency Telegram alert is sent when Telegram secrets are configured.
"""

from __future__ import annotations

import json
import os
import sys
import time as time_module
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

API_URL = "https://api.twelvedata.com/time_series"
STATE_PATH = Path("signal_state.json")
EVENTS_PATH = Path("signal_events.json")
NY = ZoneInfo("America/New_York")
MAX_EVENT_HISTORY = 500
REQUEST_TIMEOUT = 30
TELEGRAM_TIMEOUT = 15
TELEGRAM_RETRIES = 3
HEALTH_PATH = Path("monitor_health.json")
HEALTH: dict[str, Any] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON in {path.name}") from exc


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def regular_market_window(now_ny: datetime) -> bool:
    if now_ny.weekday() >= 5:
        return False
    current = now_ny.time().replace(tzinfo=None)
    return time(9, 30) <= current <= time(16, 5)


def fetch_today_minute_bars(symbol: str, api_key: str) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": 390,
        "timezone": "America/New_York",
        "apikey": api_key,
    }
    response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if data.get("status") == "error":
        raise RuntimeError(
            f"Twelve Data error for {symbol}: {data.get('code', '')} {data.get('message', 'unknown error')}"
        )
    values = data.get("values") or []
    bars: list[dict[str, Any]] = []
    for row in values:
        bars.append(
            {
                "datetime": str(row["datetime"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        )
    bars.sort(key=lambda x: x["datetime"])
    return bars


def append_event(events_payload: dict[str, Any], event: dict[str, Any]) -> None:
    events = events_payload.setdefault("events", [])
    events.append(event)
    events_payload["events"] = events[-MAX_EVENT_HISTORY:]
    events_payload["updated_at_utc"] = utc_now()


def telegram_credentials() -> tuple[str, str]:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def telegram_message(event: dict[str, Any]) -> str:
    symbol = event["symbol"]
    stop = float(event["stop_usd"])
    low = float(event["trigger_bar_low_usd"])
    last = float(event["last_observed_close_usd"])
    bar_time = event["trigger_bar_datetime_ny"]
    return (
        "🚨 STOP ATINGIDO — STOCK SIGNALS\n\n"
        f"🔴 SAÍDA: {symbol}\n"
        f"Stop: US${stop:.4f}\n"
        f"Mínima do candle: US${low:.4f}\n"
        f"Último preço observado: US${last:.4f}\n"
        f"Horário NY: {bar_time}\n\n"
        "AÇÃO: vender a posição fracionária manualmente na Wealthsimple assim que possível.\n\n"
        "Signal-only: confirme a execução manual no broker."
    )


def send_telegram(event: dict[str, Any]) -> bool:
    token, chat_id = telegram_credentials()
    if not token or not chat_id:
        event["telegram_alert_status"] = "not_configured"
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": telegram_message(event),
        "disable_web_page_preview": True,
    }

    last_error: str | None = None
    for attempt in range(1, TELEGRAM_RETRIES + 1):
        try:
            response = requests.post(url, data=payload, timeout=TELEGRAM_TIMEOUT)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                raise RuntimeError(f"Telegram API returned ok=false: {body}")
            event["telegram_alert_status"] = "sent"
            event["telegram_alert_sent_at_utc"] = utc_now()
            result = body.get("result") or {}
            if result.get("message_id") is not None:
                event["telegram_message_id"] = result["message_id"]
            print(f"Telegram emergency alert sent for {event['symbol']}")
            return True
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt < TELEGRAM_RETRIES:
                time_module.sleep(attempt * 2)

    event["telegram_alert_status"] = "failed"
    event["telegram_alert_last_error"] = f"{last_error}: delivery failed"
    print(f"WARNING: Telegram alert failed for {event['symbol']}", file=sys.stderr)
    return False


def retry_unsent_exit_alerts(events_payload: dict[str, Any]) -> bool:
    token, chat_id = telegram_credentials()
    if not token or not chat_id:
        return False

    changed = False
    for event in events_payload.get("events", []):
        if event.get("type") != "EXIT":
            continue
        if event.get("telegram_alert_status") == "sent":
            continue
        send_telegram(event)
        changed = True
    if changed:
        events_payload["updated_at_utc"] = utc_now()
    return changed


def main() -> int:
    HEALTH.update({"started_at_utc": utc_now(), "status": "running", "symbols": {},
                   "telegram_configured": all(telegram_credentials()),
                   "target_interval_seconds": 300})
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        HEALTH.update({"status": "error", "error": "missing_market_data_key"})
        print("ERROR: TWELVE_DATA_API_KEY is missing", file=sys.stderr)
        return 2

    if not STATE_PATH.exists():
        raise RuntimeError("signal_state.json missing")
    state = load_json(STATE_PATH, {"version": 1, "positions": {}, "closed_signals": []})
    events_payload = load_json(EVENTS_PATH, {"version": 1, "events": []})

    # Retry any previous EXIT alert that was committed but could not be delivered.
    retry_changed = retry_unsent_exit_alerts(events_payload)

    now_ny = datetime.now(NY)
    if not regular_market_window(now_ny):
        HEALTH["status"] = "outside_session"
        if retry_changed:
            save_json(EVENTS_PATH, events_payload)
        print(f"Outside regular US market window: {now_ny.isoformat()}")
        return 0

    positions: dict[str, dict[str, Any]] = state.setdefault("positions", {})
    closed = state.setdefault("closed_signals", [])

    if not positions:
        HEALTH["status"] = "no_signals"
        if retry_changed:
            save_json(EVENTS_PATH, events_payload)
        print("No active or pending strategy signals to monitor.")
        return 0

    today = now_ny.date().isoformat()
    changed = retry_changed
    new_exit_events: list[dict[str, Any]] = []

    for symbol, pos in list(positions.items()):
        status = pos.get("status")
        if status not in {"pending_entry", "active"}:
            continue

        signal_date = str(pos.get("signal_date") or "")
        if today <= signal_date:
            continue

        try:
            bars = fetch_today_minute_bars(symbol, api_key)
        except Exception as exc:
            HEALTH["symbols"][symbol] = {"status": "error", "error": type(exc).__name__}
            print(f"WARNING: {symbol}: market data request failed", file=sys.stderr)
            continue

        today_bars = [
            b for b in bars
            if b["datetime"][:10] == today and "09:30" <= b["datetime"][11:16] <= "16:00"
        ]
        if not today_bars:
            HEALTH["symbols"][symbol] = {"status": "no_fresh_data"}
            print(f"{symbol}: no fresh regular-session minute bars today.")
            continue

        latest_time = datetime.fromisoformat(today_bars[-1]["datetime"]).replace(tzinfo=NY)
        age_seconds = (now_ny - latest_time).total_seconds()
        HEALTH["symbols"][symbol] = {
            "status": "ok" if -60 <= age_seconds <= 600 else "stale",
            "checked_at_utc": utc_now(), "bar_datetime_ny": today_bars[-1]["datetime"],
            "bar_age_seconds": round(age_seconds), "last_price_usd": today_bars[-1]["close"],
            "stop_usd": pos["stop_usd"],
        }

        if status == "pending_entry":
            pos["status"] = "active"
            pos["activated_date"] = today
            pos["activated_at_utc"] = utc_now()
            pos["entry_note"] = (
                "Signal-only activation at the next regular market session; actual broker fill is not tracked."
            )
            pos["updated_at_utc"] = utc_now()
            changed = True

        stop = float(pos["stop_usd"])
        trigger_bar = next((b for b in today_bars if float(b["low"]) <= stop), None)

        if trigger_bar is None:
            latest = today_bars[-1]
            print(
                f"{symbol}: latest={latest['datetime']} close={latest['close']:.4f}, "
                f"session_low={min(b['low'] for b in today_bars):.4f}, stop={stop:.4f}"
            )
            continue

        event_time = utc_now()
        exit_event = {
            "id": f"EXIT-{symbol}-{event_time}",
            "type": "EXIT",
            "symbol": symbol,
            "reason": "stop_crossed_intraday",
            "stop_usd": round(stop, 4),
            "trigger_bar_datetime_ny": trigger_bar["datetime"],
            "trigger_bar_low_usd": round(float(trigger_bar["low"]), 4),
            "last_observed_close_usd": round(float(today_bars[-1]["close"]), 4),
            "original_signal_date": signal_date,
            "action": "sell_fractional_position_manually_as_soon_as_practical",
            "created_at_utc": event_time,
            "telegram_alert_status": "pending",
        }
        append_event(events_payload, exit_event)
        new_exit_events.append(exit_event)

        closed_record = dict(pos)
        closed_record["status"] = "exit_triggered"
        closed_record["exit_triggered_at_utc"] = event_time
        closed_record["exit_stop_usd"] = round(stop, 4)
        closed_record["exit_trigger_bar_datetime_ny"] = trigger_bar["datetime"]
        closed.append(closed_record)
        del positions[symbol]
        changed = True
        print(f"EXIT {symbol}: low={trigger_bar['low']:.4f} <= stop={stop:.4f}")

    # Send emergency alerts immediately after exit events are created. The EXIT
    # remains recorded even if Telegram is temporarily unavailable; failed alerts
    # are retried on the next workflow run.
    for event in new_exit_events:
        send_telegram(event)
        changed = True

    if changed:
        state["updated_at_utc"] = utc_now()
        state["closed_signals"] = closed[-200:]
        events_payload["updated_at_utc"] = utc_now()
        save_json(STATE_PATH, state)
        save_json(EVENTS_PATH, events_payload)
        print("Updated signal_state.json and signal_events.json")
    else:
        print("No state changes.")

    unhealthy = any(v["status"] != "ok" for v in HEALTH["symbols"].values())
    HEALTH["status"] = "degraded" if unhealthy else "ok"
    return 1 if unhealthy else 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception as exc:
        HEALTH.update({"status": "error", "error": type(exc).__name__})
        result = 1
    finally:
        HEALTH["completed_at_utc"] = utc_now()
        save_json(HEALTH_PATH, HEALTH)
    raise SystemExit(result)
