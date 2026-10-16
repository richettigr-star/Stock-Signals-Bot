#!/usr/bin/env python3
"""Stop monitoring with dated stop levels, recovery window and one notification outbox."""
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from common import (NY, append_event, completed_scan_day, load_json, monitor_window, next_open, now_utc,
                    parse_time, regular_bar, save_json, session_bounds, utc_now, validate_ohlc)
from notifications import credentials, deliver

API_URL = "https://api.twelvedata.com/time_series"
HEALTH = {}

def fetch_today_minute_bars(symbol, api_key):
    # Recover ~2 regular sessions after a delayed scheduler, instead of discarding yesterday.
    params = {"symbol":symbol,"interval":"1min","outputsize":1000,"timezone":"America/New_York",
              "prepost":"false","adjust":"splits","apikey":api_key}
    for attempt in range(3):
        try:
            response = requests.get(API_URL,params=params,timeout=25)
            if response.status_code != 200:
                raise RuntimeError("Market-data HTTP " + str(response.status_code))
            data = response.json()
            if data.get("status") == "error" or not data.get("values"):
                raise RuntimeError("No valid market-data result")
            if str(data.get("meta",{}).get("symbol",symbol)).upper() != symbol:
                raise ValueError("Symbol mismatch")
            bars = []
            seen = set()
            for raw in data["values"]:
                stamp = raw["datetime"]
                if stamp in seen:
                    raise ValueError("Duplicate minute bar")
                seen.add(stamp)
                row = {k:float(raw[k]) for k in ("open","high","low","close")}
                row["datetime"] = stamp
                validate_ohlc(row)
                bars.append(row)
            return sorted(bars,key=lambda r:r["datetime"])
        except Exception as exc:
            safe_error = type(exc).__name__ + ": market data unavailable or invalid"
            if attempt < 2:
                time.sleep(10 if getattr(locals().get("response"),"status_code",0) != 429 else 65)
    raise RuntimeError(safe_error) from None

def bar_time(bar):
    value = datetime.fromisoformat(bar["datetime"])
    return value.replace(tzinfo=NY) if value.tzinfo is None else value

def dated_stops(pos):
    first = next_open(pos["signal_date"])
    history = [{"stop_usd":float(pos.get("initial_stop_usd",pos["stop_usd"])),
                "effective_from_utc":first.isoformat()}]
    history.extend(pos.get("stop_history",[]))
    if not pos.get("stop_history") and float(pos["stop_usd"]) != history[0]["stop_usd"]:
        history.append({"stop_usd":float(pos["stop_usd"]),
                        "effective_from_utc":next_open(pos["last_stop_update_date"]).isoformat()})
    return sorted(history,key=lambda h:parse_time(h["effective_from_utc"]))

def applicable_stop(pos, stamp):
    history = [h for h in dated_stops(pos) if parse_time(h["effective_from_utc"]) <= stamp]
    return float(history[-1]["stop_usd"]) if history else None

def main(catch_up=False, defer_notifications=False):
    now = now_utc()
    previous = load_json("monitor_health.json",{})
    HEALTH.clear()
    HEALTH.update(started_at_utc=utc_now(),status="running",symbols={},
                  telegram_configured=all(credentials()),target_interval_seconds=300,
                  active_holdings=[],unconfirmed_signals_skipped=[])
    state = load_json("signal_state.json",required=True)
    portfolio = load_json("portfolio_state.json",required=True)
    events = load_json("signal_events.json",{"version":1,"events":[]})
    positions = state.setdefault("positions",{})
    holdings = portfolio.get("holdings",{})
    api_key = __import__("os").getenv("TWELVE_DATA_API_KEY","").strip()
    in_session = monitor_window(now) or (catch_up and completed_scan_day(now) is not None)
    errors = []

    confirmed_symbols = []
    for symbol,holding in holdings.items():
        if holding.get("status") in {"closed","exit_alert_awaiting_manual_sale"}:
            continue
        confirmed_symbols.append(symbol)
        pos = positions.get(symbol)
        if not pos:
            errors.append(symbol + ":confirmed_holding_not_monitored")
        elif pos.get("status") not in {"active","pending_entry"}:
            errors.append(symbol + ":confirmed_holding_state_invalid")
    HEALTH["active_holdings"] = sorted(confirmed_symbols)

    if in_session and not all(credentials()):
        errors.append("telegram_not_configured")
    changed = False
    # An inconsistent legacy active signal may still be checked as a fail-safe, so keep the
    # market-data dependency while any active strategy state exists.
    active_strategy_symbols = [s for s,p in positions.items() if p.get("status") == "active"]
    if in_session and (confirmed_symbols or active_strategy_symbols) and not api_key:
        errors.append("market_data_key_missing")
    if in_session and api_key:
        checked_count = 0
        for symbol,pos in list(positions.items()):
            if pos.get("status") not in {"active","pending_entry"}:
                continue
            holding = holdings.get(symbol)
            confirmed = bool(holding and holding.get("status") not in {"closed","exit_alert_awaiting_manual_sale"})
            # Pending strategy signals are recommendations, not positions. Never fetch/trigger
            # stop data for them until the user confirms the purchase.
            if pos.get("status") == "pending_entry" and not confirmed:
                HEALTH["unconfirmed_signals_skipped"].append(symbol)
                continue
            # A legacy/inconsistent active signal without a holding is checked only as a
            # theoretical fail-safe; notifications must never tell the user to sell it.
            if pos["status"] == "pending_entry" and confirmed:
                pos.update(status="active",activated_date=holding.get("entry_date"),
                           activated_at_utc=utc_now(),
                           entry_note="User-confirmed holding; broker fill is tracked from portfolio_state.json.")
                changed = True
            effective_open = next_open(pos["signal_date"])
            if now < effective_open:
                continue
            if checked_count:
                time.sleep(9.5)
            checked_count += 1
            try:
                bars = fetch_today_minute_bars(symbol,api_key)
                valid = [b for b in bars if regular_bar(b["datetime"])
                         and effective_open <= bar_time(b) <= now]
                if not valid:
                    raise ValueError("no_fresh_regular_session_bars")
                latest = valid[-1]
                bounds = session_bounds(now.astimezone(NY).date())
                expected = min(now,bounds[1])
                age = (expected - bar_time(latest)).total_seconds()
                cursor = parse_time(pos.get("last_checked_bar_utc"))
                if cursor and bar_time(latest) < cursor:
                    raise ValueError("Market data went backwards")
                start = cursor or effective_open
                missing_start = (bar_time(valid[0]) - start).total_seconds() > 600
                # Ignore overnight/weekend minutes; identify long holes within a regular session.
                recent = [b for b in valid if bar_time(b) >= start]
                long_hole = any(bar_time(a).date() == bar_time(b).date()
                                and (bar_time(b)-bar_time(a)).total_seconds() > 600
                                for a,b in zip(recent,recent[1:]))
                today_bars = [b for b in recent if bar_time(b).astimezone(NY).date() == now.astimezone(NY).date()]
                if today_bars and start < bounds[0] and (bar_time(today_bars[0])-bounds[0]).total_seconds() > 600:
                    long_hole = True
                quote_status = "ok" if 0 <= age <= 180 and not missing_start and not long_hole else "stale_or_gap"
                HEALTH["symbols"][symbol] = {"status":quote_status,"checked_at_utc":utc_now(),
                    "bar_datetime_ny":latest["datetime"],"bar_age_seconds":round(age),
                    "last_price_usd":latest["close"],"stop_usd":float(pos["stop_usd"]),
                    "holding_confirmed":confirmed,
                    "recovery_gap_detected":missing_start or long_hole}
                if quote_status != "ok":
                    errors.append(symbol + ":stale_or_gap")
                trigger = None
                fill_time = parse_time(pos.get("actual_fill",{}).get("execution_time"))
                for bar in recent:
                    stamp = bar_time(bar)
                    if fill_time and stamp < fill_time:
                        continue
                    stop = applicable_stop(pos,stamp)
                    if stop is not None and bar["low"] <= stop:
                        trigger = (bar,stop)
                        break
                # Repeat the last (possibly unclosed) bar on the next pass.
                pos["last_checked_bar_utc"] = bar_time(latest).astimezone(timezone.utc).isoformat()
                pos["updated_at_utc"] = utc_now()
                changed = True
                if trigger:
                    bar,stop = trigger
                    signal_id = pos.get("signal_id",f"ENTRY-{symbol}-{pos['signal_date']}")
                    event = {"id":f"EXIT-{signal_id}-{bar['datetime']}","type":"EXIT","symbol":symbol,
                        "signal_id":signal_id,"holding_confirmed":confirmed,
                        "entry_time_known":fill_time is not None,"stop_usd":round(stop,4),
                        "trigger_bar_datetime_ny":bar["datetime"],"trigger_bar_low_usd":bar["low"],
                        "last_observed_close_usd":latest["close"],"original_signal_date":pos["signal_date"],
                        "created_at_utc":utc_now(),"telegram_alert_status":"pending"}
                    append_event(events,event)
                    record = dict(pos)
                    record.update(status="exit_triggered",exit_stop_usd=stop,
                                  exit_triggered_at_utc=utc_now(),exit_event_id=event["id"],
                                  exit_trigger_bar_datetime_ny=bar["datetime"])
                    state.setdefault("closed_signals",[]).append(record)
                    del positions[symbol]
                print(symbol + ": data=" + quote_status + "; exit=" + str(trigger is not None))
            except Exception as exc:
                HEALTH["symbols"][symbol] = {"status":"error","error":type(exc).__name__,
                                             "holding_confirmed":confirmed}
                errors.append(symbol + ":data_error")
                print(symbol + ": market data unavailable",file=sys.stderr)
    HEALTH["unconfirmed_signals_skipped"] = sorted(set(HEALTH["unconfirmed_signals_skipped"]))
    status = ("degraded" if errors else ("ok" if confirmed_symbols else "no_active_holdings")) if in_session else "outside_session"
    HEALTH["status"] = status
    if errors and previous.get("status") != "degraded":
        append_event(events,{"id":"MONITOR-HEALTH-"+utc_now(),"type":"MONITOR_HEALTH",
                     "component":"monitor","detail":"Leitura incompleta ou atrasada: " + ", ".join(errors),
                     "created_at_utc":utc_now(),"telegram_alert_status":"pending"})
    save_json("signal_events.json",events)
    if changed:
        state["updated_at_utc"] = utc_now()
        save_json("signal_state.json",state)
    # Retry ENTRY/STOP_UPDATE too; do not wait until the next daily run.
    if defer_notifications:
        HEALTH["notifications_ok"] = None
        return 0 if not errors else 1
    delivered = deliver(events)
    save_json("signal_events.json",events)
    HEALTH["notifications_ok"] = delivered
    if not delivered and in_session:
        HEALTH["status"] = "degraded"
    return 0 if not errors and delivered else 1

def run(catch_up=False, defer_notifications=False):
    result = 1
    try:
        result = main(catch_up=catch_up, defer_notifications=defer_notifications)
    except Exception as exc:
        HEALTH.update(status="error",error=type(exc).__name__)
        print("Monitor failed: " + type(exc).__name__,file=sys.stderr)
    finally:
        HEALTH["completed_at_utc"] = utc_now()
        save_json("monitor_health.json",HEALTH)
    return result

if __name__ == "__main__":
    raise SystemExit(run(defer_notifications="--defer-notifications" in sys.argv))
