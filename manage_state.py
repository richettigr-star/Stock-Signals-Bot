#!/usr/bin/env python3
"""Maintain signal-only state after the daily scanner runs.

Safety rules:
- never create entries from an incomplete or stale daily scan;
- never keep more than 3 pending/active strategy slots;
- reconcile same-day rescans before the next market open;
- never replay stale Telegram alerts when Telegram is configured later;
- never print Telegram credentials in errors/logs.
"""

from __future__ import annotations

import json
import os
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

STATE_PATH = Path("signal_state.json")
EVENTS_PATH = Path("signal_events.json")
SIGNALS_PATH = Path("signals.json")
ATR_MULTIPLIER = 2.5
MAX_SLOTS = 3
MAX_EVENT_HISTORY = 500
TELEGRAM_TIMEOUT = 15
TELEGRAM_RETRIES = 3
ALERT_FRESHNESS = {
    "ENTRY": timedelta(hours=2),
    "ENTRY_CANCELLED": timedelta(hours=2),
    "STOP_UPDATE": timedelta(hours=2),
    "EXIT": timedelta(hours=1),
}


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
    if event["id"] in {e.get("id") for e in events}:
        return False
    events.append(event)
    events_payload["events"] = events[-MAX_EVENT_HISTORY:]
    events_payload["updated_at_utc"] = utc_now()
    return True


def get_recommended_position(candidate: dict[str, Any], signals: dict[str, Any]) -> float:
    live_small = candidate.get("sizing_cad", {}).get("LIVE Small", {})
    if "recommended_position_cad" in live_small:
        return float(live_small["recommended_position_cad"])
    count = max(1, int(signals.get("candidate_count") or 1))
    equity = float(signals.get("account_equity_cad") or 0.0)
    return round(equity / count, 2) if equity > 0 else 0.0


def telegram_credentials() -> tuple[str, str]:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def telegram_message(event: dict[str, Any]) -> str:
    event_type = event.get("type")
    if event_type == "ENTRY":
        return (
            "🟢 NOVA ENTRADA — STOCK SIGNALS\n\n"
            f"Ativo: {event['symbol']}\n"
            f"Sinal confirmado: {event['signal_date']}\n"
            "Execução: próxima abertura regular\n"
            f"Valor sugerido: C${float(event['recommended_position_cad']):.2f}\n"
            f"Momentum10: {float(event['momentum10_pct']):.3f}%\n"
            f"ATR14: US${float(event['atr14']):.4f}\n"
            f"Stop inicial: US${float(event['stop_usd']):.4f}\n\n"
            "Signal-only: a compra é manual na Wealthsimple."
        )
    if event_type == "ENTRY_CANCELLED":
        return (
            "⚪ ENTRADA CANCELADA — STOCK SIGNALS\n\n"
            f"Ativo: {event['symbol']}\n"
            f"Sinal: {event['signal_date']}\n"
            "Motivo: o ativo saiu do Top 3 após a leitura diária completa.\n\n"
            "Ignore qualquer alerta anterior de entrada para este sinal."
        )
    if event_type == "STOP_UPDATE":
        return (
            "🟡 TRAILING STOP ATUALIZADO — STOCK SIGNALS\n\n"
            f"Ativo: {event['symbol']}\n"
            f"Candle diário: {event['bar_date']}\n"
            f"Stop anterior: US${float(event['old_stop_usd']):.4f}\n"
            f"Novo stop: US${float(event['new_stop_usd']):.4f}\n"
            f"Fechamento: US${float(event['close_usd']):.4f}\n"
            f"ATR14: US${float(event['atr14']):.4f}\n\n"
            "Regra: o trailing stop nunca desce."
        )
    if event_type == "EXIT":
        return (
            "🚨 STOP ATINGIDO — STOCK SIGNALS\n\n"
            f"🔴 SAÍDA: {event['symbol']}\n"
            f"Stop: US${float(event['stop_usd']):.4f}\n"
            f"Mínima do candle: US${float(event['trigger_bar_low_usd']):.4f}\n"
            f"Último preço observado: US${float(event['last_observed_close_usd']):.4f}\n"
            f"Horário NY: {event['trigger_bar_datetime_ny']}\n\n"
            "AÇÃO: vender a posição fracionária manualmente na Wealthsimple assim que possível."
        )
    return f"Stock Signals event: {event.get('type')} {event.get('symbol')}"


def send_telegram(event: dict[str, Any]) -> bool:
    token, chat_id = telegram_credentials()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": telegram_message(event), "disable_web_page_preview": True}

    for attempt in range(1, TELEGRAM_RETRIES + 1):
        try:
            response = requests.post(url, data=payload, timeout=TELEGRAM_TIMEOUT)
            if response.status_code >= 400:
                raise RuntimeError(f"Telegram HTTP {response.status_code}")
            body = response.json()
            if not body.get("ok"):
                raise RuntimeError("Telegram API returned ok=false")
            event["telegram_alert_status"] = "sent"
            event["telegram_alert_sent_at_utc"] = utc_now()
            result = body.get("result") or {}
            if result.get("message_id") is not None:
                event["telegram_message_id"] = result["message_id"]
            print(f"Telegram {event.get('type')} alert sent for {event.get('symbol')}")
            return True
        except Exception as exc:
            safe_error = f"{type(exc).__name__}: Telegram delivery failed"
            if attempt < TELEGRAM_RETRIES:
                time_module.sleep(attempt * 2)

    event["telegram_alert_status"] = "failed"
    event["telegram_alert_last_error"] = safe_error
    print(f"WARNING: Telegram {event.get('type')} alert failed for {event.get('symbol')}: {safe_error}")
    return False


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def retry_unsent_notifications(events_payload: dict[str, Any]) -> bool:
    token, chat_id = telegram_credentials()
    if not token or not chat_id:
        return False

    changed = False
    now = datetime.now(timezone.utc)
    for event in events_payload.get("events", []):
        event_type = event.get("type")
        if event_type not in ALERT_FRESHNESS:
            continue
        if event.get("telegram_alert_status") in {"sent", "skipped_stale", "skipped_superseded"}:
            continue
        created = parse_utc(event.get("created_at_utc"))
        if created is None or now - created > ALERT_FRESHNESS[event_type]:
            event["telegram_alert_status"] = "skipped_stale"
            event["telegram_alert_last_error"] = "Not delivered because the event is no longer fresh."
            changed = True
            continue
        send_telegram(event)
        changed = True

    if changed:
        events_payload["updated_at_utc"] = utc_now()
    return changed


def scan_is_complete_and_fresh(signals: dict[str, Any]) -> tuple[bool, str]:
    latest = str(signals.get("latest_bar_date") or "")
    today_ny = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    universe = list(signals.get("strategy", {}).get("universe") or [])
    rows = list(signals.get("all_symbols") or [])
    errors = list(signals.get("errors") or [])
    row_symbols = {r.get("symbol") for r in rows if r.get("symbol")}
    all_same_date = bool(rows) and all(str(r.get("bar_date") or "") == latest for r in rows)

    if latest != today_ny:
        return False, f"latest bar {latest or 'N/A'} is not New York date {today_ny}"
    if errors:
        return False, f"scanner reported {len(errors)} data error(s)"
    if universe and row_symbols != set(universe):
        return False, f"scanner returned {len(row_symbols)}/{len(universe)} universe symbols"
    if not all_same_date:
        return False, "not all symbols have the same completed daily bar"
    return True, "complete"


def main() -> int:
    signals = load_json(SIGNALS_PATH, {})
    if not signals.get("latest_bar_date"):
        raise SystemExit("signals.json does not contain a completed scan")

    state = load_json(STATE_PATH, {"version": 1, "positions": {}, "closed_signals": []})
    events_payload = load_json(EVENTS_PATH, {"version": 1, "events": []})
    positions: dict[str, dict[str, Any]] = state.setdefault("positions", {})
    all_symbols = {r["symbol"]: r for r in signals.get("all_symbols", []) if r.get("symbol")}
    latest_bar_date = str(signals["latest_bar_date"])
    scan_ok, scan_reason = scan_is_complete_and_fresh(signals)

    # Update trailing stops only when the daily scan is complete and fresh.
    if scan_ok:
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
            pos.update({
                "stop_usd": round(new_stop, 4),
                "atr14_latest": float(row["atr14"]),
                "last_close_usd": float(row["close_usd"]),
                "last_stop_update_date": row_date,
                "updated_at_utc": utc_now(),
            })
            if new_stop > old_stop + 1e-9:
                append_event(events_payload, {
                    "id": f"STOP_UPDATE-{symbol}-{row_date}", "type": "STOP_UPDATE", "symbol": symbol,
                    "bar_date": row_date, "old_stop_usd": round(old_stop, 4), "new_stop_usd": round(new_stop, 4),
                    "close_usd": float(row["close_usd"]), "atr14": float(row["atr14"]), "created_at_utc": utc_now(),
                })

    if scan_ok:
        candidates = list(signals.get("candidates") or [])
        candidate_map = {c["symbol"]: c for c in candidates}

        # Older pending signals and active signals occupy strategy slots.
        carry_symbols = [
            symbol for symbol, pos in positions.items()
            if pos.get("status") == "active"
            or (pos.get("status") == "pending_entry" and str(pos.get("signal_date") or "") < latest_bar_date)
        ]
        slots_left = max(0, MAX_SLOTS - len(carry_symbols))
        desired_today = [c["symbol"] for c in candidates if c["symbol"] not in carry_symbols][:slots_left]

        # Same-day rescans can change ranking. Remove pending entries that are no
        # longer in the final desired set before the next market open.
        for symbol, pos in list(positions.items()):
            if (
                pos.get("status") == "pending_entry"
                and str(pos.get("signal_date") or "") == latest_bar_date
                and symbol not in desired_today
            ):
                positions.pop(symbol, None)
                for event in events_payload.get("events", []):
                    if event.get("id") == f"ENTRY-{symbol}-{latest_bar_date}" and event.get("telegram_alert_status") != "sent":
                        event["telegram_alert_status"] = "skipped_superseded"
                append_event(events_payload, {
                    "id": f"ENTRY_CANCELLED-{symbol}-{latest_bar_date}",
                    "type": "ENTRY_CANCELLED", "symbol": symbol, "signal_date": latest_bar_date,
                    "created_at_utc": utc_now(),
                })

        # Create/update only the desired same-day pending entries.
        for symbol in desired_today:
            candidate = candidate_map[symbol]
            current = positions.get(symbol)
            if current and current.get("status") in {"pending_entry", "active"}:
                # Refresh same-day pending values after a complete re-scan.
                if current.get("status") == "pending_entry" and str(current.get("signal_date")) == latest_bar_date:
                    current.update({
                        "signal_close_usd": float(candidate["close_usd"]),
                        "atr14_at_signal": float(candidate["atr14"]),
                        "atr14_latest": float(candidate["atr14"]),
                        "stop_usd": float(candidate["reference_stop_usd"]),
                        "initial_stop_usd": float(candidate["reference_stop_usd"]),
                        "recommended_position_cad": round(get_recommended_position(candidate, signals), 2),
                        "score": float(candidate["score"]),
                        "momentum10_pct": float(candidate["momentum10_pct"]),
                        "updated_at_utc": utc_now(),
                    })
                continue

            recommended_cad = get_recommended_position(candidate, signals)
            position = {
                "symbol": symbol, "status": "pending_entry", "signal_date": latest_bar_date,
                "planned_entry": "next_market_open", "signal_close_usd": float(candidate["close_usd"]),
                "atr14_at_signal": float(candidate["atr14"]), "atr14_latest": float(candidate["atr14"]),
                "stop_usd": float(candidate["reference_stop_usd"]), "initial_stop_usd": float(candidate["reference_stop_usd"]),
                "last_stop_update_date": latest_bar_date, "recommended_position_cad": round(recommended_cad, 2),
                "score": float(candidate["score"]), "momentum10_pct": float(candidate["momentum10_pct"]),
                "stop_rule": "max(previous_stop, completed_daily_close - 2.5 * ATR14)",
                "created_at_utc": utc_now(), "updated_at_utc": utc_now(),
            }
            positions[symbol] = position
            append_event(events_payload, {
                "id": f"ENTRY-{symbol}-{latest_bar_date}", "type": "ENTRY", "symbol": symbol,
                "signal_date": latest_bar_date, "effective": "next_market_open",
                "signal_close_usd": position["signal_close_usd"], "atr14": position["atr14_at_signal"],
                "stop_usd": position["stop_usd"], "recommended_position_cad": position["recommended_position_cad"],
                "momentum10_pct": position["momentum10_pct"], "score": position["score"], "created_at_utc": utc_now(),
            })
    else:
        print(f"WARNING: refusing new entries/stop updates: {scan_reason}")

    retry_unsent_notifications(events_payload)
    state["updated_at_utc"] = utc_now()
    state["latest_processed_bar_date"] = latest_bar_date
    state["scan_validation"] = {"accepted": scan_ok, "reason": scan_reason}
    state["state_note"] = "Signal-only strategy state. This does not represent actual broker fills or holdings."

    save_json(STATE_PATH, state)
    save_json(EVENTS_PATH, events_payload)
    active_count = sum(1 for p in positions.values() if p.get("status") in {"pending_entry", "active"})
    print(f"State updated. Active/pending strategy slots: {active_count}/{MAX_SLOTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
