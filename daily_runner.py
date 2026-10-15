#!/usr/bin/env python3
"""Calendar-aware daily runner with retryable health and failure alerts."""
import os
from common import append_event, completed_scan_day, load_json, now_utc, save_json, utc_now
from notifications import deliver
import intraday_exit
import manage_state
import rate_limited_scanner

def main():
    day = completed_scan_day(now_utc())
    health = load_json("daily_health.json",{})
    if day is None:
        print("No completed session available today; daily scan skipped.")
        return 0
    if health.get("bar_date") == day and health.get("scan_accepted") and os.getenv("FORCE_DAILY_SCAN") != "true":
        print("Completed daily scan already processed; duplicate scan skipped.")
        return 0
    # Check old stops before raising them from today's close.
    # During a late run outside the grace window, the next monitor still recovers old bars using stop_history.
    try:
        intraday_exit.run(catch_up=True)
        if intraday_exit.HEALTH.get("status") == "error" or any(
            value.get("status") != "ok" for value in intraday_exit.HEALTH.get("symbols",{}).values()
        ):
            raise RuntimeError("Cannot reconcile old stops before daily update")
        code = rate_limited_scanner.scanner.main()
        if code:
            raise RuntimeError("Incomplete daily market data")
        state_code = manage_state.main()
        if state_code and not load_json("daily_health.json",{}).get("scan_accepted"):
            raise RuntimeError("Daily scan validation failed")
        return state_code
    except Exception as exc:
        save_json("daily_health.json",{"completed_at_utc":utc_now(),"status":"error",
                   "scan_accepted":False,"bar_date":day,"reason":type(exc).__name__})
        events = load_json("signal_events.json",{"events":[]})
        append_event(events,{"id":"DAILY-FAIL-"+day,"type":"MONITOR_HEALTH","component":"daily scanner",
                     "detail":"Falha no scan diário. Nenhuma nova entrada foi aceita; uma nova tentativa está agendada.",
                     "created_at_utc":utc_now(),"telegram_alert_status":"pending"})
        save_json("signal_events.json",events)
        deliver(events)
        save_json("signal_events.json",events)
        return 1
if __name__ == "__main__":
    raise SystemExit(main())
