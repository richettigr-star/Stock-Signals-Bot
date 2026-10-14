#!/usr/bin/env python3
"""Intraday EXIT signal monitor.

Checks only strategy signals remembered in signal_state.json. It does not place
broker orders. When a 1-minute bar trades at or below the stored stop, the
signal is closed in strategy state and an EXIT event is appended to
signal_events.json.
"""

from __future__ import annotations

import json
import os
import sys
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def regular_market_window(now_ny: datetime) -> bool:
    if now_ny.weekday() >= 5:
        return False
    current = now_ny.time().replace(tzinfo=None)
    return time(9, 30) <= current <= time(16, 5)


def fetch_recent_minute_bars(symbol: str, api_key: str) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "interval": "1min",
        "outputsize": 60,
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


def main() -> int:
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        print("ERROR: TWELVE_DATA_API_KEY is missing", file=sys.stderr)
        return 2

    now_ny = datetime.now(NY)
    if not regular_market_window(now_ny):
        print(f"Outside regular US market window: {now_ny.isoformat()}")
        return 0

    state = load_json(STATE_PATH, {"version": 1, "positions": {}, "closed_signals": []})
    events_payload = load_json(EVENTS_PATH, {"version": 1, "events": []})
    positions: dict[str, dict[str, Any]] = state.setdefault("positions", {})
    closed = state.setdefault("closed_signals", [])

    if not positions:
        print("No active or pending strategy signals to monitor.")
        return 0

    today = now_ny.date().isoformat()
    changed = False

    for symbol, pos in list(positions.items()):
        status = pos.get("status")
        if status not in {"pending_entry", "active"}:
            continue

        signal_date = str(pos.get("signal_date") or "")
        # A nightly signal becomes active only on a later trading day. Fresh
        # minute bars below ensure a holiday does not activate a stale signal.
        if today <= signal_date:
            continue

        try:
            bars = fetch_recent_minute_bars(symbol, api_key)
        except Exception as exc:
            print(f"WARNING: {symbol}: {exc}", file=sys.stderr)
            continue

        today_bars = [b for b in bars if b["datetime"][:10] == today and b["datetime"][11:16] >= "09:30"]
        if not today_bars:
            print(f"{symbol}: no fresh regular-session minute bars today; leaving pending/active state unchanged.")
            continue

        if status == "pending_entry":
            pos["status"] = "active"
            pos["activated_date"] = today
            pos["activated_at_utc"] = utc_now()
            pos["entry_note"] = (
                "Signal-only activation at the next regular market session; actual broker fill is not tracked."
            )
            changed = True

        last_seen = str(pos.get("last_intraday_bar_datetime") or "")
        unseen = [b for b in today_bars if not last_seen or b["datetime"] > last_seen]
        if not unseen:
            continue

        stop = float(pos["stop_usd"])
        trigger_bar = next((b for b in unseen if float(b["low"]) <= stop), None)
        pos["last_intraday_bar_datetime"] = unseen[-1]["datetime"]
        pos["last_observed_price_usd"] = unseen[-1]["close"]
        pos["updated_at_utc"] = utc_now()
        changed = True

        if trigger_bar is None:
            print(
                f"{symbol}: monitored through {unseen[-1]['datetime']}; "
                f"last={unseen[-1]['close']:.4f}, stop={stop:.4f}"
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
            "last_observed_close_usd": round(float(trigger_bar["close"]), 4),
            "original_signal_date": signal_date,
            "action": "sell_fractional_position_manually_as_soon_as_practical",
            "created_at_utc": event_time,
        }
        append_event(events_payload, exit_event)

        closed_record = dict(pos)
        closed_record["status"] = "exit_triggered"
        closed_record["exit_triggered_at_utc"] = event_time
        closed_record["exit_stop_usd"] = round(stop, 4)
        closed_record["exit_trigger_bar_datetime_ny"] = trigger_bar["datetime"]
        closed.append(closed_record)
        del positions[symbol]
        changed = True
        print(f"EXIT {symbol}: low={trigger_bar['low']:.4f} <= stop={stop:.4f}")

    if changed:
        state["updated_at_utc"] = utc_now()
        state["closed_signals"] = closed[-200:]
        save_json(STATE_PATH, state)
        save_json(EVENTS_PATH, events_payload)
        print("Updated signal_state.json and signal_events.json")
    else:
        print("No state changes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
