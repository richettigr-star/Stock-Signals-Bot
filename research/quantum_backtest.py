#!/usr/bin/env python3
"""Research-only 24-month backtest using the LIVE Stock Signals rules.

This file is intentionally isolated from the production scanner. It does not alter
SYMBOLS, signal state, portfolio state, notifications, or the dashboard.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

API_URL = "https://api.twelvedata.com/time_series"
BASELINE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "NFLX",
    "JPM", "BAC", "XOM", "CVX", "UNH", "LLY", "COST", "WMT", "PLTR", "COIN",
]
NEW = ["QBTS", "IONQ", "RGTI", "MU"]
ALL = BASELINE + NEW
MOMENTUM_LOOKBACK = 10
MOMENTUM_THRESHOLD = 0.02
EMA_PERIOD = 100
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.5
MAX_SLOTS = 3
INITIAL_EQUITY = 100.0
RISK_TARGET = 7.5  # LIVE Small = 7.5% of the C$100 reference account
OUTPUTSIZE = 750
RATE_LIMIT_SLEEP = 8.2
REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
END_DATE = date(2026, 10, 16)  # latest completed regular session before Sun 2026-10-18
START_DATE = date(2024, 10, 18)
WARMUP_START = START_DATE - timedelta(days=220)


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def wilder_atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> list[float | None]:
    trs = []
    for i in range(len(closes)):
        if i == 0:
            tr = highs[i] - lows[i]
        else:
            pc = closes[i - 1]
            tr = max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc))
        trs.append(tr)
    atr: list[float | None] = [None] * len(trs)
    if len(trs) < period:
        return atr
    prev = sum(trs[:period]) / period
    atr[period - 1] = prev
    for i in range(period, len(trs)):
        prev = ((prev * (period - 1)) + trs[i]) / period
        atr[i] = prev
    return atr


def fetch(symbol: str, api_key: str) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": OUTPUTSIZE,
        "adjust": "splits",
        "apikey": api_key,
    }
    last = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            payload = r.json()
            if payload.get("status") == "error":
                raise RuntimeError(f"Twelve Data {payload.get('code')}: {payload.get('message','error')}")
            values = payload.get("values") or []
            if not values:
                raise RuntimeError("no values")
            rows = []
            for x in values:
                d = date.fromisoformat(x["datetime"][:10])
                if d < WARMUP_START or d > END_DATE:
                    continue
                rows.append({
                    "date": d.isoformat(),
                    "open": float(x["open"]),
                    "high": float(x["high"]),
                    "low": float(x["low"]),
                    "close": float(x["close"]),
                    "volume": float(x.get("volume") or 0),
                })
            rows.sort(key=lambda x: x["date"])
            if len(rows) < 120:
                raise RuntimeError(f"only {len(rows)} usable bars")
            return rows
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES:
                time.sleep(10 * attempt)
    raise RuntimeError(f"{symbol} fetch failed: {last}")


def add_indicators(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    e = ema(closes, EMA_PERIOD)
    a = wilder_atr(highs, lows, closes, ATR_PERIOD)
    out = []
    for i, r in enumerate(rows):
        rr = dict(r)
        rr["ema100"] = e[i]
        rr["atr14"] = a[i]
        if i >= MOMENTUM_LOOKBACK and a[i] and r["close"] > 0:
            mom = r["close"] / closes[i - MOMENTUM_LOOKBACK] - 1.0
            atr_pct = float(a[i]) / r["close"]
            rr["momentum10"] = mom
            rr["score"] = mom / atr_pct if atr_pct > 0 else float("-inf")
            rr["eligible"] = mom > MOMENTUM_THRESHOLD and r["close"] > e[i]
            rr["signal_stop"] = r["close"] - ATR_MULTIPLIER * float(a[i])
            rr["stop_pct"] = (ATR_MULTIPLIER * float(a[i])) / r["close"]
        else:
            rr.update(momentum10=None, score=None, eligible=False, signal_stop=None, stop_pct=None)
        out.append(rr)
    return out


def usable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if START_DATE.isoformat() <= r["date"] <= END_DATE.isoformat()]


@dataclass
class Trade:
    symbol: str
    signal_date: str
    entry_date: str
    entry: float
    initial_stop: float
    exit_date: str | None = None
    exit: float | None = None
    return_pct: float | None = None
    exit_reason: str | None = None


def single_symbol_backtest(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    rows = [r for r in rows if r["date"] <= END_DATE.isoformat()]
    index = {r["date"]: i for i, r in enumerate(rows)}
    trade: Trade | None = None
    pending: dict[str, Any] | None = None
    trades: list[Trade] = []
    equity = 1.0
    curve = []

    for i, r in enumerate(rows):
        d = r["date"]
        if d < START_DATE.isoformat():
            continue

        if pending and pending["entry_date"] == d and trade is None:
            trade = Trade(symbol=symbol, signal_date=pending["signal_date"], entry_date=d,
                          entry=r["open"], initial_stop=pending["stop"])
            trade._stop = pending["stop"]  # type: ignore[attr-defined]
            pending = None

        if trade is not None:
            stop = float(trade._stop)  # type: ignore[attr-defined]
            exit_px = None
            reason = None
            if r["open"] <= stop:
                exit_px, reason = r["open"], "gap_below_stop"
            elif r["low"] <= stop:
                exit_px, reason = stop, "stop"
            if exit_px is not None:
                ret = exit_px / trade.entry - 1.0
                equity *= 1.0 + ret
                trade.exit_date = d
                trade.exit = round(exit_px, 6)
                trade.return_pct = ret * 100
                trade.exit_reason = reason
                trades.append(trade)
                trade = None
            else:
                if r["atr14"]:
                    trade._stop = max(stop, r["close"] - ATR_MULTIPLIER * float(r["atr14"]))  # type: ignore[attr-defined]

        # Signal after the close. If flat, schedule next actual trading day open.
        if trade is None and pending is None and r.get("eligible"):
            if i + 1 < len(rows):
                nxt = rows[i + 1]
                if nxt["date"] <= END_DATE.isoformat():
                    pending = {"signal_date": d, "entry_date": nxt["date"], "stop": float(r["signal_stop"])}

        mark = equity
        if trade is not None:
            mark = equity * (r["close"] / trade.entry)
        curve.append(mark)

    open_return = None
    if trade is not None:
        last = next(r for r in reversed(rows) if r["date"] <= END_DATE.isoformat())
        open_return = last["close"] / trade.entry - 1.0
        equity *= 1.0 + open_return

    peak, max_dd = 0.0, 0.0
    for x in curve:
        peak = max(peak, x)
        if peak > 0:
            max_dd = min(max_dd, x / peak - 1.0)
    wins = [t for t in trades if (t.return_pct or 0) > 0]
    losses = [t for t in trades if (t.return_pct or 0) <= 0]
    bh_rows = usable_rows(rows)
    bh = (bh_rows[-1]["close"] / bh_rows[0]["open"] - 1.0) if bh_rows else None
    returns = [float(t.return_pct) for t in trades if t.return_pct is not None]
    return {
        "symbol": symbol,
        "trades_closed": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "strategy_return_pct": round((equity - 1.0) * 100, 2),
        "buy_hold_return_pct": round(bh * 100, 2) if bh is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "avg_closed_trade_pct": round(sum(returns) / len(returns), 2) if returns else None,
        "best_trade_pct": round(max(returns), 2) if returns else None,
        "worst_trade_pct": round(min(returns), 2) if returns else None,
        "open_position_mark_to_market_pct": round(open_return * 100, 2) if open_return is not None else None,
        "trades": [asdict(t) for t in trades],
    }


def portfolio_backtest(data: dict[str, list[dict[str, Any]]], universe: list[str], name: str) -> dict[str, Any]:
    by_date = {s: {r["date"]: r for r in data[s]} for s in universe}
    dates = sorted({d for s in universe for d in by_date[s] if START_DATE.isoformat() <= d <= END_DATE.isoformat()})
    positions: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    cash = INITIAL_EQUITY
    trades = []
    curve = []

    for d in dates:
        # Entries at today's open, using the allocation reserved by yesterday's signal.
        todays_pending = [p for p in pending if p["entry_date"] == d]
        pending = [p for p in pending if p["entry_date"] != d]
        for p in todays_pending:
            if p["symbol"] in positions or len(positions) >= MAX_SLOTS:
                continue
            r = by_date[p["symbol"]].get(d)
            if not r:
                continue
            amount = min(p["allocation"], cash)
            if amount < 0.01:
                continue
            cash -= amount
            positions[p["symbol"]] = {
                "symbol": p["symbol"], "signal_date": p["signal_date"], "entry_date": d,
                "entry": r["open"], "qty": amount / r["open"], "cost": amount,
                "stop": p["stop"], "initial_stop": p["stop"],
            }

        # Intraday stop processing.
        for symbol in list(positions):
            r = by_date[symbol].get(d)
            if not r:
                continue
            pos = positions[symbol]
            stop = pos["stop"]
            exit_px = None
            reason = None
            if r["open"] <= stop:
                exit_px, reason = r["open"], "gap_below_stop"
            elif r["low"] <= stop:
                exit_px, reason = stop, "stop"
            if exit_px is not None:
                proceeds = pos["qty"] * exit_px
                cash += proceeds
                ret = exit_px / pos["entry"] - 1.0
                trades.append({
                    "symbol": symbol, "signal_date": pos["signal_date"], "entry_date": pos["entry_date"],
                    "entry": pos["entry"], "exit_date": d, "exit": exit_px,
                    "return_pct": ret * 100, "pnl_cad": proceeds - pos["cost"], "exit_reason": reason,
                })
                del positions[symbol]

        # Trailing stops update after completed close, effective next session.
        for symbol, pos in positions.items():
            r = by_date[symbol].get(d)
            if r and r.get("atr14"):
                pos["stop"] = max(pos["stop"], r["close"] - ATR_MULTIPLIER * float(r["atr14"]))

        # Scanner ranks all eligible symbols first, exactly like production; existing holdings can occupy Top 3.
        eligible = []
        for symbol in universe:
            r = by_date[symbol].get(d)
            if r and r.get("eligible"):
                eligible.append((float(r["score"]), symbol, r))
        top3 = sorted(eligible, key=lambda x: (-x[0], x[1]))[:MAX_SLOTS]
        carry = set(positions) | {p["symbol"] for p in pending}
        free = max(0, MAX_SLOTS - len(carry))
        selected = [(s, r) for _, s, r in top3 if s not in carry][:free]

        if selected:
            # Find each symbol's next available trading date.
            available_cash = cash - sum(p["allocation"] for p in pending)
            available_cash = max(0.0, available_cash)
            slot = math.floor(available_cash * 100 / len(selected) + 1e-8) / 100
            for symbol, r in selected:
                sym_dates = sorted(x for x in by_date[symbol] if x > d and x <= END_DATE.isoformat())
                if not sym_dates:
                    continue
                stop_pct = float(r["stop_pct"])
                risk_based = RISK_TARGET / stop_pct if stop_pct > 0 else 0.0
                allocation = min(slot, risk_based)
                if allocation < 0.01:
                    continue
                pending.append({
                    "symbol": symbol, "signal_date": d, "entry_date": sym_dates[0],
                    "stop": float(r["signal_stop"]), "allocation": allocation,
                })

        # End-of-day marked equity.
        equity = cash
        for symbol, pos in positions.items():
            r = by_date[symbol].get(d)
            if r:
                equity += pos["qty"] * r["close"]
            else:
                equity += pos["cost"]
        curve.append({"date": d, "equity": equity})

    final_equity = curve[-1]["equity"] if curve else INITIAL_EQUITY
    peak = INITIAL_EQUITY
    max_dd = 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        max_dd = min(max_dd, p["equity"] / peak - 1.0)
    wins = [t for t in trades if t["return_pct"] > 0]
    return {
        "name": name,
        "universe_size": len(universe),
        "start_equity_cad": INITIAL_EQUITY,
        "final_equity_cad": round(final_equity, 2),
        "return_pct": round((final_equity / INITIAL_EQUITY - 1.0) * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "closed_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "open_positions": sorted(positions),
        "closed_trade_detail": trades,
        "equity_curve": curve,
    }


def main() -> int:
    key = os.getenv("TWELVE_DATA_API_KEY")
    if not key:
        raise SystemExit("TWELVE_DATA_API_KEY missing")
    data: dict[str, list[dict[str, Any]]] = {}
    errors = []
    for n, symbol in enumerate(ALL):
        try:
            print(f"Fetching {symbol} ({n+1}/{len(ALL)})", flush=True)
            rows = fetch(symbol, key)
            data[symbol] = add_indicators(rows)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
        if n + 1 < len(ALL):
            time.sleep(RATE_LIMIT_SLEEP)

    missing = [s for s in ALL if s not in data]
    if missing:
        Path("research/quantum_backtest_error.json").write_text(json.dumps({"errors": errors}, indent=2) + "\n")
        raise SystemExit("Missing symbols: " + ", ".join(missing))

    per_symbol = [single_symbol_backtest(data[s], s) for s in NEW]
    baseline = portfolio_backtest(data, BASELINE, "baseline_20")
    augmented = portfolio_backtest(data, ALL, "augmented_24")
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat()},
        "data_source": "Twelve Data daily OHLC, adjust=splits",
        "strategy": {
            "momentum10_threshold_pct": 2.0,
            "trend": "close > EMA100",
            "ranking": "Momentum10 / (ATR14 / Close)",
            "atr": "Wilder 14",
            "stop": "2.5 x ATR14; trailing only rises after completed daily close",
            "entry": "next available regular-session open",
            "direction": "long only",
            "max_slots": 3,
            "risk_profile": "LIVE Small 7.5% of C$100 reference account",
            "gap_rule": "if next session opens below stop, exit at open; otherwise stop fill at stop",
        },
        "assumptions": [
            "All generated entries are assumed manually confirmed/fillable at the next regular-session open.",
            "No commissions, slippage, bid/ask spread, taxes, currency conversion, or Wealthsimple FX costs.",
            "Daily OHLC cannot reconstruct the exact intraday path; stop execution follows the conservative gap rule above.",
            "Research only: production universe and LIVE state are unchanged.",
        ],
        "new_symbols": per_symbol,
        "portfolio_comparison": {"baseline_20": baseline, "augmented_24": augmented},
        "errors": errors,
    }
    out = Path("research/quantum_backtest_results.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# 24-Month Research Backtest — QBTS / IONQ / RGTI / MU",
        "",
        f"Period: {START_DATE.isoformat()} through {END_DATE.isoformat()}",
        "Data: Twelve Data daily OHLC, split-adjusted (same provider/adjustment style as production)",
        "",
        "## New-symbol results",
        "",
        "| Symbol | Closed trades | Win rate | Strategy return | Buy & hold | Max drawdown |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for x in per_symbol:
        lines.append(f"| {x['symbol']} | {x['trades_closed']} | {x['win_rate_pct']}% | {x['strategy_return_pct']}% | {x['buy_hold_return_pct']}% | {x['max_drawdown_pct']}% |")
    lines += [
        "", "## Portfolio comparison", "",
        "| Portfolio | Final equity | Return | Max drawdown | Closed trades | Win rate |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Baseline 20 | C${baseline['final_equity_cad']:.2f} | {baseline['return_pct']}% | {baseline['max_drawdown_pct']}% | {baseline['closed_trades']} | {baseline['win_rate_pct']}% |",
        f"| Baseline + QBTS/IONQ/RGTI/MU | C${augmented['final_equity_cad']:.2f} | {augmented['return_pct']}% | {augmented['max_drawdown_pct']}% | {augmented['closed_trades']} | {augmented['win_rate_pct']}% |",
        "", "## Important assumptions", "",
        "- Signal after completed daily close; entry at next regular-session open.",
        "- Stop starts at signal close minus 2.5×ATR14 and only moves upward after completed daily bars.",
        "- If a session opens below the stop, the backtest exits at the open rather than pretending a fill at the higher stop.",
        "- No commissions, slippage, spread, tax, CAD/USD conversion, or Wealthsimple FX costs.",
        "- This research branch does not modify the production universe or LIVE signals.",
    ]
    Path("research/quantum_backtest_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "new_symbols": [{k: x[k] for k in ("symbol","trades_closed","win_rate_pct","strategy_return_pct","buy_hold_return_pct","max_drawdown_pct")} for x in per_symbol],
        "baseline": {k: baseline[k] for k in ("final_equity_cad","return_pct","max_drawdown_pct","closed_trades","win_rate_pct")},
        "augmented": {k: augmented[k] for k in ("final_equity_cad","return_pct","max_drawdown_pct","closed_trades","win_rate_pct")},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
