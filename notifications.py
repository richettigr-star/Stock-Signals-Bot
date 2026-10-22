"""One Telegram outbox for entry, stop, exit and monitor health alerts."""
import os
import time
from datetime import datetime, timedelta
import requests
from common import NY, next_open, now_utc, parse_time, save_json, utc_now

def credentials():
    return (os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip())
def message(event):
    kind, symbol = event.get("type"), event.get("symbol", "")
    if kind == "ENTRY":
        return (f"🟢 ENTRADA — STOCK SIGNALS\n{symbol}\nSinal: {event['signal_date']}\n"
                f"Próxima abertura regular. Valor sugerido: C$ {event['recommended_position_cad']:.2f}\n"
                f"Stop do sinal: US$ {event['stop_usd']:.4f}\nID: {event['id']}\nCompra manual; confirme preço e execução.")
    if kind == "STOP_UPDATE":
        scope = "Posição confirmada" if event.get("holding_confirmed") else "Sinal teórico — compra não confirmada"
        return (f"🟡 TRAILING STOP — {symbol}\n{scope}\n"
                f"Anterior: US$ {event['old_stop_usd']:.4f}\nNovo: US$ {event['new_stop_usd']:.4f}\n"
                f"Candle diário: {event['bar_date']}\nID: {event['id']}")
    if kind == "ENTRY_CANCELLED":
        return f"⚪ SINAL CANCELADO — {symbol}\nIgnore a entrada de {event['signal_date']}.\nID: {event['id']}"
    if kind == "EXIT":
        confirmed = event.get("holding_confirmed", False)
        scope = "🚨 STOP ATINGIDO — posição confirmada" if confirmed else "⚪ STOP ATINGIDO — sinal teórico, compra não confirmada"
        action = "Confira sua posição e execute a saída manualmente." if confirmed else "Não há compra confirmada; este aviso não presume uma posição a vender."
        delay = "\n⚠️ Entrega atrasada; verifique o horário do cruzamento." if event.get("delivery_delayed") else ""
        return (f"{scope}\n{symbol}\nStop: US$ {event['stop_usd']:.4f}\n"
                f"Mínima observada: US$ {event['trigger_bar_low_usd']:.4f}\n"
                f"Cruzamento NY: {event['trigger_bar_datetime_ny']}{delay}\n{action}\nID: {event['id']}")
    if kind == "MONITOR_HEALTH":
        return f"⚠️ STOCK SIGNALS — {event['component']}\n{event['detail']}\nUTC: {event['created_at_utc']}\nNenhuma ordem foi executada."
    return f"Stock Signals: {kind} {symbol}"

def send(event):
    token, chat = credentials()
    event["telegram_last_attempt_at_utc"] = utc_now()
    if not token or not chat:
        event["telegram_alert_status"] = "not_configured"
        return False
    for attempt in range(3):
        try:
            response = requests.post("https://api.telegram.org/bot" + token + "/sendMessage",
                data={"chat_id": chat, "text": message(event), "disable_web_page_preview": True}, timeout=15)
            body = response.json()
            if response.status_code != 200 or not body.get("ok"):
                raise RuntimeError("Telegram rejected message")
            event.update(telegram_alert_status="sent", telegram_alert_sent_at_utc=utc_now(),
                         telegram_message_id=body.get("result", {}).get("message_id"))
            event.pop("telegram_alert_last_error", None)
            return True
        except Exception as exc:
            event["telegram_alert_last_error"] = type(exc).__name__ + ": Telegram delivery failed"
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    event["telegram_alert_status"] = "failed"
    return False

def deliver(payload, on_update=None):
    if on_update is None and os.getenv("STOCK_DURABLE_OUTBOX") == "true":
        on_update = lambda updated: save_json("signal_events.json", updated)
    now = now_utc()
    events = payload.get("events", [])
    for event in events:
        if event.get("telegram_alert_status") in {"sent", "skipped_stale", "skipped_superseded"}:
            continue
        kind = event.get("type")
        if kind not in {"ENTRY", "STOP_UPDATE", "ENTRY_CANCELLED", "EXIT", "MONITOR_HEALTH"}:
            continue
        created = parse_time(event.get("created_at_utc"))
        if kind in {"ENTRY", "ENTRY_CANCELLED"} and now >= next_open(event["signal_date"]):
            event["telegram_alert_status"] = "skipped_stale"
            continue
        if kind == "STOP_UPDATE" and any(e.get("symbol") == event.get("symbol") and (
            (e.get("type") == "STOP_UPDATE" and str(e.get("bar_date")) > str(event.get("bar_date")))
            or (e.get("type") == "EXIT" and str(e.get("created_at_utc")) >= str(event.get("created_at_utc")))
        ) for e in events):
            event["telegram_alert_status"] = "skipped_superseded"
            continue
        if kind == "EXIT":
            trigger = datetime.fromisoformat(event["trigger_bar_datetime_ny"])
            if trigger.tzinfo is None:
                trigger = trigger.replace(tzinfo=NY)
            event["delivery_delayed"] = created is None or now - min(created, trigger) > timedelta(minutes=10)
        last_attempt = parse_time(event.get("telegram_last_attempt_at_utc"))
        if last_attempt and now - last_attempt < timedelta(minutes=2):
            continue
        send(event)
        if on_update:
            on_update(payload)
    payload["updated_at_utc"] = utc_now()
    return not any(e.get("telegram_alert_status") in {"failed", "not_configured", "pending"} for e in events
                   if e.get("type") in {"ENTRY", "STOP_UPDATE", "EXIT", "MONITOR_HEALTH"})
