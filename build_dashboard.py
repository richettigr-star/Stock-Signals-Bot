#!/usr/bin/env python3
"""Reconcile confirmed holdings with signals; never infer a broker sale."""
import json
from datetime import datetime, timezone
from pathlib import Path

def read(name, default):
    p = Path(name)
    return json.loads(p.read_text()) if p.exists() else default

def write(name, value):
    Path(name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

def main():
    portfolio = read("portfolio_state.json", {})
    state = read("signal_state.json", {})
    health = read("monitor_health.json", {})
    events = read("signal_events.json", {"events": []}).get("events", [])
    now = datetime.now(timezone.utc)
    last = health.get("completed_at_utc")
    stale = not last or (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() > 600
    status = health.get("status", "not_verified")
    if stale and status != "outside_session":
        status = "stale_or_unverified"
    portfolio["updated_at_utc"] = now.isoformat()
    portfolio["exit_monitor_status"] = status
    portfolio["monitor_last_completed_at_utc"] = last
    portfolio["telegram_status"] = "configured_delivery_unverified" if health.get("telegram_configured") else "not_configured"
    rows = []
    for symbol, holding in portfolio.get("holdings", {}).items():
        signal = state.get("positions", {}).get(symbol, {})
        closed = [p for p in state.get("closed_signals", []) if p.get("symbol") == symbol]
        matching = [e for e in events if e.get("symbol") == symbol and e.get("type") == "EXIT"
                    and str(e.get("created_at_utc", ""))[:10] >= holding["entry_date"]]
        event = matching[-1] if matching else None
        if holding.get("status") != "closed":
            holding["status"] = "exit_alert_awaiting_manual_sale" if event else "active"
        stop = signal.get("stop_usd")
        if stop is None and closed:
            stop = closed[-1].get("exit_stop_usd")
        if stop is not None:
            holding["strategy_stop_usd"] = stop
        quote = health.get("symbols", {}).get(symbol, {})
        holding["latest_price_usd"] = quote.get("last_price_usd")
        holding["quote_datetime_ny"] = quote.get("bar_datetime_ny")
        holding["quote_status"] = quote.get("status", "unavailable")
        holding["exit_alert"] = event
        if event:
            portfolio["telegram_status"] = event.get("telegram_alert_status", "pending")
        price = holding["latest_price_usd"]
        pct = (price / holding["entry_price_usd"] - 1) * 100 if price is not None else None
        holding["price_return_since_entry_pct"] = round(pct, 4) if pct is not None else None
        display_price = f'{price:.4f}' if price is not None else "Unavailable"
        display_return = f'{pct:+.2f}%' if pct is not None else "Unavailable"
        rows.append(f'| {symbol} | {holding["status"]} | {holding["entry_price_usd"]:.2f} | {display_price} | {holding["strategy_stop_usd"]:.4f} | {display_return} |')
    write("portfolio_state.json", portfolio)
    lines = [
        "# Stock Signals — Dashboard", "",
        f'Generated UTC: {now.isoformat()}', "",
        f'**Monitor: {status}**. Last completed check UTC: {last or "NEVER VERIFIED"}.',
        "Target interval: 5 minutes during regular US trading. If the last check is older than 10 minutes during the session, treat monitoring as unavailable.",
        f'Notifications: **{portfolio["telegram_status"]}**.', "",
        f'Capital: C$100.00 · Invested cost: C$33.33 · Unallocated: C$66.67',
        f'Realized P&L: C$0.00 · Closed trades: 0 · Wins: 0 · Losses: 0', "",
        "| Holding | Status | Entry USD | Last observed USD | Strategy stop USD | Price return since entry |",
        "|---|---|---:|---:|---:|---:|",
        *rows, "",
        "WMT/XOM: unexecuted strategy signals; no confirmed holdings.", "",
        "An EXIT alert is not a confirmed sale. Holdings, cash and realized P&L change only after the user confirms execution.",
        "Return is the USD stock-price change, not exact CAD account P&L. Quote time/status are stored in portfolio_state.json.",
        "Today’s return: unavailable without a verified previous close.", "",
        "## Latest EXIT alerts", "",
    ]
    exits = [e for e in events if e.get("type") == "EXIT"][-10:]
    lines += [f'- {e["symbol"]}: stop USD {e["stop_usd"]:.4f}; NY {e["trigger_bar_datetime_ny"]}; notification: {e.get("telegram_alert_status", "pending")}.' for e in reversed(exits)] or ["No recorded EXIT alerts."]
    lines += ["", "This file refreshes when a workflow completes. Reload the page to see the saved result; this chat is not a live display.", ""]
    Path("dashboard.md").write_text("\n".join(lines))

if __name__ == "__main__":
    main()
