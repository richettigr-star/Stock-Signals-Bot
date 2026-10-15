#!/usr/bin/env python3
"""Maintain daily strategy state only from a complete, closed-session scan."""
import math
from common import (append_event, completed_scan_day, load_json, next_open,
                    now_utc, save_json, utc_now)
from notifications import deliver
from scanner import SYMBOLS

MAX_SLOTS = 3

def scan_is_complete_and_fresh(signals):
    expected_day = completed_scan_day(now_utc())
    if expected_day is None:
        return False, "market session has not closed plus 15-minute data allowance, or non-trading day"
    if signals.get("latest_bar_date") != expected_day:
        return False, "daily bars are stale"
    if signals.get("errors"):
        return False, "market-data errors"
    rows = signals.get("all_symbols", [])
    if len(rows) != len(SYMBOLS) or {r.get("symbol") for r in rows} != set(SYMBOLS):
        return False, "incomplete or duplicate universe"
    if any(r.get("bar_date") != expected_day for r in rows):
        return False, "mixed bar dates"
    candidates = signals.get("candidates", [])
    if len({r["symbol"] for r in candidates}) != len(candidates):
        return False, "duplicate candidates"
    expected = sorted([r for r in rows if r.get("eligible")],
                      key=lambda r:(-r["score"],r["symbol"]))[:MAX_SLOTS]
    if [r["symbol"] for r in candidates] != [r["symbol"] for r in expected]:
        return False, "candidate ranking mismatch"
    for row in rows:
        if not all(math.isfinite(float(row[key])) and row[key] > 0
                   for key in ("close_usd","atr14","reference_stop_usd")):
            return False, "invalid daily prices/ATR"
    return True, "complete closed-session scan"

def confirmed_holdings(portfolio):
    return {s:h for s,h in portfolio.get("holdings", {}).items()
            if h.get("status") not in {"closed", "exit_alert_awaiting_manual_sale"}}

def expire_unconfirmed_positions(positions, holdings, candidates, day, events):
    """Expire signals that were never manually confirmed as purchases."""
    desired = {r["symbol"] for r in candidates}
    for symbol, pos in list(positions.items()):
        if symbol in holdings:
            continue
        signal_day = str(pos.get("signal_date", ""))
        stale = signal_day < day
        superseded = signal_day == day and symbol not in desired
        if not (stale or superseded):
            continue
        if superseded:
            append_event(events, {
                "id":f"ENTRY_CANCELLED-{symbol}-{day}",
                "type":"ENTRY_CANCELLED","symbol":symbol,"signal_date":day,
                "created_at_utc":utc_now(),"telegram_alert_status":"pending"
            })
        del positions[symbol]

def main():
    signals = load_json("signals.json", required=True)
    state = load_json("signal_state.json", required=True)
    events = load_json("signal_events.json", {"version":1,"events":[]})
    portfolio = load_json("portfolio_state.json", required=True)
    ok, reason = scan_is_complete_and_fresh(signals)
    day = signals.get("latest_bar_date")
    if ok:
        positions = state.setdefault("positions", {})
        rows = {r["symbol"]:r for r in signals["all_symbols"]}
        holdings = confirmed_holdings(portfolio)

        # A signal does not become a holding by itself. Old unconfirmed signals
        # must release their slot before today's Top 3 is allocated.
        expire_unconfirmed_positions(positions, holdings, signals["candidates"], day, events)

        # Only user-confirmed holdings receive trailing-stop updates.
        for symbol in holdings:
            pos = positions.get(symbol)
            if not pos:
                continue
            row = rows[symbol]
            if day <= str(pos.get("last_stop_update_date", "")):
                continue
            old = float(pos["stop_usd"])
            new = round(max(old, row["close_usd"] - 2.5 * row["atr14"]),4)
            pos.update(stop_usd=new, atr14_latest=row["atr14"], last_close_usd=row["close_usd"],
                       last_stop_update_date=day, updated_at_utc=utc_now())
            if new > old:
                history = pos.setdefault("stop_history", [])
                history.append({"stop_usd":new,"effective_from_utc":next_open(day).isoformat(),"bar_date":day})
                append_event(events, {"id":f"STOP_UPDATE-{symbol}-{day}","type":"STOP_UPDATE","symbol":symbol,
                    "bar_date":day,"old_stop_usd":old,"new_stop_usd":new,"close_usd":row["close_usd"],
                    "atr14":row["atr14"],"holding_confirmed":True,"created_at_utc":utc_now(),
                    "telegram_alert_status":"pending"})

        # Same-day pending entries reserve slots and cash; yesterday's
        # unconfirmed entries were removed above.
        current_pending = {s:p for s,p in positions.items()
                           if s not in holdings and p.get("status") == "pending_entry"
                           and str(p.get("signal_date")) == day}
        carry = set(holdings) | set(current_pending)
        blocked = {s for s,h in portfolio.get("holdings", {}).items()
                   if h.get("status") == "exit_alert_awaiting_manual_sale"}
        selected = [r for r in signals["candidates"]
                    if r["symbol"] not in carry | blocked][:max(0,MAX_SLOTS-len(carry))]

        cash = max(0.0, float(portfolio.get("unallocated_capital_cad", 0)))
        reserved = sum(float(p.get("recommended_position_cad", 0)) for p in current_pending.values())
        available = max(0.0, cash - reserved)
        slot = math.floor(available * 100 / len(selected) + 1e-8) / 100 if selected else 0
        for candidate in selected:
            symbol = candidate["symbol"]
            allocation = min(slot, candidate["sizing_cad"]["LIVE Small"]["risk_based_position_cad"])
            if allocation < .01:
                continue
            event_id = f"ENTRY-{symbol}-{day}"
            if any(e.get("id") == event_id for e in events.get("events",[])):
                continue
            stop = candidate["reference_stop_usd"]
            pos = {"symbol":symbol,"signal_id":event_id,"status":"pending_entry","signal_date":day,
                   "planned_entry":"next_market_open","signal_close_usd":candidate["close_usd"],
                   "atr14_at_signal":candidate["atr14"],"atr14_latest":candidate["atr14"],
                   "stop_usd":stop,"initial_stop_usd":stop,"last_stop_update_date":day,
                   "recommended_position_cad":round(allocation,2),"score":candidate["score"],
                   "momentum10_pct":candidate["momentum10_pct"],"created_at_utc":utc_now(),
                   "updated_at_utc":utc_now(),
                   "stop_rule":"max(previous_stop, completed_daily_close - 2.5 * ATR14)",
                   "stop_history":[{"stop_usd":stop,"effective_from_utc":next_open(day).isoformat(),"bar_date":day}]}
            positions[symbol] = pos
            append_event(events, {"id":event_id,"type":"ENTRY","symbol":symbol,"signal_date":day,
                "signal_close_usd":candidate["close_usd"],"stop_usd":stop,"atr14":candidate["atr14"],
                "momentum10_pct":candidate["momentum10_pct"],"recommended_position_cad":round(allocation,2),
                "created_at_utc":utc_now(),"telegram_alert_status":"pending"})
        state["latest_processed_bar_date"] = day
    state.update(updated_at_utc=utc_now(),scan_validation={"accepted":ok,"reason":reason})
    save_json("signal_state.json",state)
    save_json("signal_events.json",events)
    delivered = deliver(events)
    save_json("signal_events.json",events)
    save_json("daily_health.json",{"completed_at_utc":utc_now(),"status":"ok" if ok and delivered else "degraded",
              "scan_accepted":ok,"bar_date":day,"reason":reason,"notifications_ok":delivered})
    print(f"Daily state: accepted={ok}; {reason}; notifications_ok={delivered}")
    return 0 if ok and delivered else 1

if __name__ == "__main__":
    raise SystemExit(main())
