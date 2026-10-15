#!/usr/bin/env python3
"""Build a dated dashboard from actual holdings, signal state and delivery receipts."""
from datetime import timedelta
from pathlib import Path
from common import NY, load_json, monitor_window, now_utc, parse_time, save_json, utc_now

def main():
    portfolio = load_json("portfolio_state.json",required=True)
    state = load_json("signal_state.json",required=True)
    health = load_json("monitor_health.json",{})
    daily = load_json("daily_health.json",{})
    events = load_json("signal_events.json",{"events":[]}).get("events",[])
    now = now_utc()
    last = parse_time(health.get("completed_at_utc"))
    status = health.get("status","unverified")
    if monitor_window(now) and (not last or now-last > timedelta(minutes=10)):
        status = "STALE — monitoring unavailable"
    holdings = portfolio.get("holdings",{})
    open_holdings = {s:h for s,h in holdings.items() if h.get("status") != "closed"}
    invested = round(sum(float(h["invested_cad"]) for h in open_holdings.values()),2)
    initial = float(portfolio.get("initial_capital_cad",0))
    realized = float(portfolio.get("realized_pnl_cad",0))
    cash = round(initial+realized+float(portfolio.get("net_deposits_cad",0))-invested,2)
    portfolio.update(updated_at_utc=utc_now(),exit_monitor_status=status,
                     monitor_last_completed_at_utc=health.get("completed_at_utc"),
                     invested_cost_cad=invested,unallocated_capital_cad=cash)
    pending = [e for e in events if e.get("telegram_alert_status") in {"pending","failed","not_configured"}]
    sent = [e for e in events if e.get("telegram_alert_status") == "sent"]
    telegram = "not_configured" if not health.get("telegram_configured") else ("delivery_pending_or_failed" if pending else "configured")
    portfolio["telegram_status"] = telegram
    portfolio["last_telegram_delivery_at_utc"] = max((e.get("telegram_alert_sent_at_utc","") for e in sent),default=None)
    rows = []
    for symbol,h in open_holdings.items():
        pos = state.get("positions",{}).get(symbol,{})
        if pos and not h.get("signal_id"):
            h["signal_id"] = pos.get("signal_id",f"ENTRY-{symbol}-{pos['signal_date']}")
        related = [e for e in events if e.get("type") == "EXIT" and e.get("symbol") == symbol
                   and (e.get("signal_id") == h.get("signal_id") if h.get("signal_id") else
                        str(e.get("created_at_utc",""))[:10] >= h["entry_date"])]
        event = related[-1] if related else None
        h["status"] = "exit_alert_awaiting_manual_sale" if event else "active"
        if pos:
            h["strategy_stop_usd"] = pos["stop_usd"]
        elif event:
            h["strategy_stop_usd"] = event["stop_usd"]
        elif not event:
            status = "DEGRADED — confirmed holding lacks monitoring signal"
            portfolio["exit_monitor_status"] = status
        quote = health.get("symbols",{}).get(symbol,{})
        if quote.get("last_price_usd") is not None:
            h["latest_price_usd"] = quote["last_price_usd"]
            h["quote_datetime_ny"] = quote["bar_datetime_ny"]
        h["quote_status"] = quote.get("status","unavailable")
        h["exit_alert"] = event
        price = h.get("latest_price_usd")
        pct = 100*(price/h["entry_price_usd"]-1) if price is not None else None
        h["price_return_since_entry_pct"] = round(pct,4) if pct is not None else None
        price_text = f"{price:.4f}" if price is not None else "unavailable"
        pct_text = f"{pct:+.2f}%" if pct is not None else "unavailable"
        rows.append(f'| {symbol} | {h["status"]} | {h["entry_price_usd"]:.2f} | {price_text} | {h["strategy_stop_usd"]:.4f} | {pct_text} | {h.get("quote_datetime_ny","unknown")} ({h["quote_status"]}) |')
    portfolio["unexecuted_signals"] = sorted(set(state.get("positions",{}))-set(open_holdings))
    save_json("portfolio_state.json",portfolio)
    lines = ["# Stock Signals — Dashboard","",f"Snapshot UTC: {utc_now()}","",
             f"**Monitor as of this snapshot: {status}**",
             f'Last check UTC: {health.get("completed_at_utc","NEVER VERIFIED")}.',
             "During the session, a last check older than 10 minutes means monitoring is unavailable, even if this saved snapshot says OK.",
             f"Telegram: **{telegram}** · Undelivered events: {len(pending)}.",
             f'Daily scan: {daily.get("status","unverified")} · Last processed bar: {state.get("latest_processed_bar_date","unknown")}.',"",
             f"Initial capital: C$ {initial:.2f} · Invested cost: C$ {invested:.2f} · Unallocated cash: C$ {cash:.2f}",
             f'Realized P&L: C$ {realized:.2f} · Closed trades: {portfolio.get("closed_trades",0)} · Wins: {portfolio.get("winning_trades",0)} · Losses: {portfolio.get("losing_trades",0)}',"",
             "| Holding | Status | Entry USD | Last observed USD | Strategy stop USD | USD return since entry | Quote NY (status) |",
             "|---|---|---:|---:|---:|---:|---|",*rows,"",
             "EXIT is an alert, not a broker sale. Cash and realized P&L change only after confirmed execution.",
             "USD price return is not exact CAD P&L; share quantity, FX and fees are not yet recorded.",
             "This chat is not continuously updating. Reload this GitHub page for the latest saved snapshot.","",
             "## Strategy signals without confirmed purchases",""]
    for s in portfolio["unexecuted_signals"]:
        p=state["positions"][s]
        lines.append(f'- {s}: {p["status"]}; strategy stop USD {p["stop_usd"]:.4f}. No real holding confirmed.')
    lines += ["","## Recent alerts",""]
    for e in events[-15:][::-1]:
        lines.append(f'- {e.get("type")} {e.get("symbol","")}: {e.get("created_at_utc","unknown")} · delivery {e.get("telegram_alert_status","pending")} · ID {e.get("id")}.')
    if not events:
        lines.append("No recorded alerts.")
    lines += ["","## Operational limits","",
              "Polling target: 5 minutes during the regular exchange session. GitHub schedules and upstream data can be delayed.",
              "Holidays and early closes use the XNYS calendar. Stops only rise from completed daily bars.",
              "Entry execution time is unknown for legacy fills; first-day monitoring assumes session open unless a precise execution timestamp is recorded.",
              "Corporate actions, trading halts and missing provider trades require reconciliation; a notification system is not a broker stop order.",""]
    Path("dashboard.md").write_text("\n".join(lines),encoding="utf-8")
if __name__ == "__main__":
    main()
