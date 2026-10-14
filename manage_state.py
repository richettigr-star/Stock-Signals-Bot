#!/usr/bin/env python3
"""Maintain signal-only state after the nightly scanner runs.

This is NOT broker portfolio tracking. It only remembers which strategy signals
are currently active so the bot can avoid duplicate ENTRY alerts and can later
produce EXIT alerts when a stop is crossed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_PATH = Path("signal_state.json")
EVENTS_PATH = Path("signal_events.json")
SIGNALS_PATH = Path("signals.json")
ATR_MULTIPLIER = 2.5
MAX_EVENT_HISTORY = 500


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


def append_event(events_payload: dict[str, Any], event: dict[str, Any]) -> bool:
    events = events_payload.setdefault("events", [])
    existing_ids = {e.get("id") for e in events}
    if event["id"] in existing_ids:
        return False
    events.append(event)
    events_payload["events"] = events[-MAX_EVENT_HISTORY:]
    events_payload["updated_at_utc"] = utc_now()
    return True


def get_recommended_position(candidate: dict[str, Any], signals: dict[str, Any]) -> float:
    sizing = candidate.get("sizing_cad", {})
    live_small = sizing.get("LIVE Small", {})
    if "recommended_position_cad" in live_small:
        return float(live_small["recommended_position_cad"])

    # Backward-compatible fallback for reports generated before slot allocation was added.
    count = max(1, int(signals.get("candidate_count") or 1))
    equity = float(signals.get("account_equity_cad") or 0.0)
    return round(equity / count, 2) if equity > 0 else 0.0


def main() -> int:
    signals = load_json(SIGNALS_PATH, {})
    if not signals.get("latest_bar_date"):
        raise SystemExit("signals.json does not contain a completed scan")

    state = load_json(
        STATE_PATH,
        {
            "version": 1,
            "positions": {},
            "closed_signals": [],
        },
    )
    events_payload = load_json(EVENTS_PATH, {"version": 1, "events": []})

    positions: dict[str, dict[str, Any]] = state.setdefault("positions", {})
    all_symbols = {r["symbol"]: r for r in signals.get("all_symbols", []) if r.get("symbol")}
    latest_bar_date = str(signals["latest_bar_date"])

    # Update trailing stops once per completed daily bar for signals that remain active.
    # Operational rule for this signal-only pilot:
    # stop_t = max(stop_{t-1}, daily_close_t - 2.5 * ATR14_t)
    for symbol, pos in list(positions.items()):
        if pos.get("status") not in {"pending_entry", "active"}:
            continue
        row = all_symbols.get(symbol)
        if not row:
            continue
        row_date = str(row.get("bar_date") or "")
        if not row_date or row_date <= str(pos.get("last_stop_update_date") or ""):
            continue

        candidate_stop = float(row["close_usd"]) - ATR_MULTIPLIER * float(row["atr14"])
        old_stop = float(pos["stop_usd"])
        new_stop = max(old_stop, candidate_stop)
        pos["stop_usd"] = round(new_stop, 4)
        pos["atr14_latest"] = float(row["atr14"])
        pos["last_close_usd"] = float(row["close_usd"])
        pos["last_stop_update_date"] = row_date
        pos["updated_at_utc"] = utc_now()

    # New nightly candidates become pending strategy entries for the next market open.
    for candidate in signals.get("candidates", []):
        symbol = candidate["symbol"]
        current = positions.get(symbol)
        if current and current.get("status") in {"pending_entry", "active"}:
            continue

        signal_date = str(candidate["bar_date"])
        recommended_cad = get_recommended_position(candidate, signals)
        position = {
            "symbol": symbol,
            "status": "pending_entry",
            "signal_date": signal_date,
            "planned_entry": "next_market_open",
            "signal_close_usd": float(candidate["close_usd"]),
            "atr14_at_signal": float(candidate["atr14"]),
            "atr14_latest": float(candidate["atr14"]),
            "stop_usd": float(candidate["reference_stop_usd"]),
            "initial_stop_usd": float(candidate["reference_stop_usd"]),
            "last_stop_update_date": signal_date,
            "recommended_position_cad": round(recommended_cad, 2),
            "score": float(candidate["score"]),
            "momentum10_pct": float(candidate["momentum10_pct"]),
            "stop_rule": "max(previous_stop, completed_daily_close - 2.5 * ATR14)",
            "created_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
        }
        positions[symbol] = position

        append_event(
            events_payload,
            {
                "id": f"ENTRY-{symbol}-{signal_date}",
                "type": "ENTRY",
                "symbol": symbol,
                "signal_date": signal_date,
                "effective": "next_market_open",
                "signal_close_usd": position["signal_close_usd"],
                "atr14": position["atr14_at_signal"],
                "stop_usd": position["stop_usd"],
                "recommended_position_cad": position["recommended_position_cad"],
                "momentum10_pct": position["momentum10_pct"],
                "score": position["score"],
                "created_at_utc": utc_now(),
            },
        )

    state["updated_at_utc"] = utc_now()
    state["latest_processed_bar_date"] = latest_bar_date
    state["state_note"] = (
        "Signal-only strategy state. This does not represent actual Wealthsimple fills or holdings."
    )

    save_json(STATE_PATH, state)
    save_json(EVENTS_PATH, events_payload)
    print(f"State updated. Active/pending signals: {len(positions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
