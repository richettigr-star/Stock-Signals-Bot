#!/usr/bin/env python3
"""Research-only robustness analysis for QBTS/IONQ/RGTI/MU.

This script does NOT change the production universe or LIVE state. It reproduces the
production scanner's indicator behavior by recalculating each historical signal from
at most the latest 180 daily bars available on that date, matching scanner.py's
OUTPUTSIZE=180, EMA100, Wilder ATR14, Momentum10 and score rules.
"""
from __future__ import annotations

import json
import math
import os
import time
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
VARIANTS = {
    "Baseline 20": BASELINE,
    "+ QBTS": BASELINE + ["QBTS"],
    "+ IONQ": BASELINE + ["IONQ"],
    "+ RGTI": BASELINE + ["RGTI"],
    "+ MU": BASELINE + ["MU"],
    "+ QBTS + RGTI": BASELINE + ["QBTS", "RGTI"],
    "+ QBTS + RGTI + MU": BASELINE + ["QBTS", "RGTI", "MU"],
    "+ all 4": ALL,
}
MOMENTUM_LOOKBACK = 10
MOMENTUM_THRESHOLD = 0.02
EMA_PERIOD = 100
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.5
SCANNER_WINDOW = 180
MIN_REQUIRED = max(EMA_PERIOD + 10, MOMENTUM_LOOKBACK + 1, ATR_PERIOD + 1)
MAX_SLOTS = 3
INITIAL_EQUITY = 100.0
RISK_TARGET_CAD = 7.5
OUTPUTSIZE = 1900
RATE_LIMIT_SLEEP = 8.2
REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
END_DATE = date(2026, 10, 16)
EARLIEST_START = date(2021, 10, 18)
FETCH_FLOOR = date(2020, 12, 1)


def ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def wilder_atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> list[float | None]:
    trs: list[float] = []
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
                if d < FETCH_FLOOR or d > END_DATE:
                    continue
                o, h, l, c = map(float, (x["open"], x["high"], x["low"], x["close"]))
                if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
                    raise ValueError(f"invalid OHLC {d}")
                rows.append({"date": d.isoformat(), "open": o, "high": h, "low": l, "close": c})
            rows.sort(key=lambda x: x["date"])
            seen = [r["date"] for r in rows]
            if len(seen) != len(set(seen)):
                raise ValueError("duplicate daily bars")
            return rows
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRIES:
                time.sleep(10 * attempt)
    raise RuntimeError(f"{symbol} fetch failed: {last}")


def add_production_indicators(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recompute each date from the latest <=180 bars exactly like scanner.py."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        rr = dict(row)
        start = max(0, i - SCANNER_WINDOW + 1)
        window = rows[start:i + 1]
        if len(window) < MIN_REQUIRED:
            rr.update(ema100=None, atr14=None, momentum10=None, score=None,
                      eligible=False, signal_stop=None, stop_pct=None)
            out.append(rr)
            continue
        closes = [r["close"] for r in window]
        highs = [r["high"] for r in window]
        lows = [r["low"] for r in window]
        e = ema(closes, EMA_PERIOD)[-1]
        a = wilder_atr(highs, lows, closes, ATR_PERIOD)[-1]
        if a is None or a <= 0 or closes[-1] <= 0:
            rr.update(ema100=e, atr14=a, momentum10=None, score=None,
                      eligible=False, signal_stop=None, stop_pct=None)
            out.append(rr)
            continue
        mom = closes[-1] / closes[-1 - MOMENTUM_LOOKBACK] - 1.0
        atr_pct = float(a) / closes[-1]
        rr.update(
            ema100=e,
            atr14=float(a),
            momentum10=mom,
            score=mom / atr_pct if atr_pct > 0 else float("-inf"),
            eligible=mom > MOMENTUM_THRESHOLD and closes[-1] > e,
            signal_stop=closes[-1] - ATR_MULTIPLIER * float(a),
            stop_pct=(ATR_MULTIPLIER * float(a)) / closes[-1],
        )
        out.append(rr)
    return out


def portfolio_backtest(data: dict[str, list[dict[str, Any]]], universe: list[str], name: str,
                       start: date, end: date) -> dict[str, Any]:
    by_date = {s: {r["date"]: r for r in data[s]} for s in universe}
    s0, s1 = start.isoformat(), end.isoformat()
    dates = sorted({d for sym in universe for d in by_date[sym] if s0 <= d <= s1})
    positions: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    cash = INITIAL_EQUITY
    trades: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []

    for d in dates:
        todays_pending = [p for p in pending if p["entry_date"] == d]
        pending = [p for p in pending if p["entry_date"] != d]
        for p in todays_pending:
            if p["symbol"] in positions or len(positions) >= MAX_SLOTS:
                continue
            r = by_date[p["symbol"]].get(d)
            if not r:
                continue
            amount = min(float(p["allocation"]), cash)
            if amount < 0.01:
                continue
            cash -= amount
            positions[p["symbol"]] = {
                "symbol": p["symbol"], "signal_date": p["signal_date"], "entry_date": d,
                "entry": r["open"], "qty": amount / r["open"], "cost": amount,
                "stop": p["stop"], "initial_stop": p["stop"],
            }

        for symbol in list(positions):
            r = by_date[symbol].get(d)
            if not r:
                continue
            pos = positions[symbol]
            stop = float(pos["stop"])
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
                    "exit_date": d, "return_pct": ret * 100, "pnl_cad": proceeds - pos["cost"],
                    "exit_reason": reason,
                })
                del positions[symbol]

        # Stop update happens after the completed close and is therefore effective next session.
        for symbol, pos in positions.items():
            r = by_date[symbol].get(d)
            if r and r.get("atr14"):
                pos["stop"] = max(float(pos["stop"]), r["close"] - ATR_MULTIPLIER * float(r["atr14"]))

        eligible = []
        for symbol in universe:
            r = by_date[symbol].get(d)
            if r and r.get("eligible"):
                eligible.append((float(r["score"]), symbol, r))
        top3 = sorted(eligible, key=lambda x: (-x[0], x[1]))[:MAX_SLOTS]
        carry = set(positions) | {p["symbol"] for p in pending}
        free = max(0, MAX_SLOTS - len(carry))
        selected = [(sym, r) for _, sym, r in top3 if sym not in carry][:free]

        if selected:
            available_cash = max(0.0, cash - sum(float(p["allocation"]) for p in pending))
            slot = math.floor(available_cash * 100 / len(selected) + 1e-8) / 100
            for symbol, r in selected:
                next_dates = sorted(x for x in by_date[symbol] if d < x <= s1)
                if not next_dates:
                    continue
                stop_pct = float(r["stop_pct"])
                risk_based = RISK_TARGET_CAD / stop_pct if stop_pct > 0 else 0.0
                allocation = min(slot, risk_based)
                if allocation >= 0.01:
                    pending.append({
                        "symbol": symbol, "signal_date": d, "entry_date": next_dates[0],
                        "stop": float(r["signal_stop"]), "allocation": allocation,
                    })

        equity = cash
        for symbol, pos in positions.items():
            r = by_date[symbol].get(d)
            equity += pos["qty"] * r["close"] if r else pos["cost"]
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
        "start": s0,
        "end": s1,
        "universe_size": len(universe),
        "final_equity_cad": round(final_equity, 2),
        "return_pct": round((final_equity / INITIAL_EQUITY - 1.0) * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "closed_trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "open_positions": sorted(positions),
    }


def variant_table(data: dict[str, list[dict[str, Any]]], start: date, end: date) -> list[dict[str, Any]]:
    return [portfolio_backtest(data, universe, name, start, end) for name, universe in VARIANTS.items()]


def signalable_date(rows: list[dict[str, Any]]) -> str | None:
    for r in rows:
        if r.get("ema100") is not None and r.get("atr14") is not None and r.get("momentum10") is not None:
            return r["date"]
    return None


def six_month_blocks() -> list[tuple[date, date]]:
    return [
        (date(2024, 10, 18), date(2025, 4, 17)),
        (date(2025, 4, 18), date(2025, 10, 17)),
        (date(2025, 10, 18), date(2026, 4, 17)),
        (date(2026, 4, 18), END_DATE),
    ]


def main() -> int:
    key = os.getenv("TWELVE_DATA_API_KEY")
    if not key:
        raise SystemExit("TWELVE_DATA_API_KEY missing")

    data: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for i, symbol in enumerate(ALL):
        try:
            print(f"Fetching {symbol} ({i+1}/{len(ALL)})", flush=True)
            data[symbol] = add_production_indicators(fetch(symbol, key))
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
        if i + 1 < len(ALL):
            time.sleep(RATE_LIMIT_SLEEP)

    missing = [s for s in ALL if s not in data]
    if missing:
        Path("research/robust_candidate_error.json").write_text(
            json.dumps({"errors": errors, "missing": missing}, indent=2) + "\n", encoding="utf-8")
        raise SystemExit("Missing symbols: " + ", ".join(missing))

    horizons = {
        "2y": date(2024, 10, 18),
        "3y": date(2023, 10, 18),
        "4y": date(2022, 10, 18),
        "5y": date(2021, 10, 18),
    }
    horizon_results = {label: variant_table(data, start, END_DATE) for label, start in horizons.items()}

    blocks = six_month_blocks()
    block_results: list[dict[str, Any]] = []
    for start, end in blocks:
        block_results.append({
            "start": start.isoformat(), "end": end.isoformat(),
            "variants": variant_table(data, start, end),
        })

    # Walk-forward selection: select the best variant on each completed 6-month block,
    # then apply only that selected variant to the following block. No future data is used.
    walk_forward: list[dict[str, Any]] = []
    for i in range(len(block_results) - 1):
        train = block_results[i]
        test = block_results[i + 1]
        chosen = max(train["variants"], key=lambda r: r["return_pct"])["name"]
        test_map = {r["name"]: r for r in test["variants"]}
        train_map = {r["name"]: r for r in train["variants"]}
        walk_forward.append({
            "train": f"{train['start']}..{train['end']}",
            "test": f"{test['start']}..{test['end']}",
            "chosen_variant": chosen,
            "train_return_pct": train_map[chosen]["return_pct"],
            "test_return_pct": test_map[chosen]["return_pct"],
            "test_baseline_return_pct": test_map["Baseline 20"]["return_pct"],
            "test_all4_return_pct": test_map["+ all 4"]["return_pct"],
        })

    coverage = {
        s: {
            "first_bar": data[s][0]["date"] if data[s] else None,
            "first_signalable": signalable_date(data[s]),
            "last_bar": data[s][-1]["date"] if data[s] else None,
            "bars": len(data[s]),
        }
        for s in NEW
    }

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": "Twelve Data daily OHLC, adjust=splits",
        "method": {
            "scanner_window": 180,
            "momentum10_threshold_pct": 2.0,
            "trend": "close > EMA100",
            "ranking": "Momentum10 / (ATR14 / Close)",
            "atr": "Wilder 14",
            "stop": "2.5 x ATR14, never lowered",
            "entry": "next regular-session open",
            "max_slots": 3,
            "risk_target_cad": 7.5,
            "production_equivalence": "each historical date recomputes indicators from latest <=180 bars",
        },
        "coverage_new_symbols": coverage,
        "horizons": horizon_results,
        "six_month_blocks": block_results,
        "walk_forward": walk_forward,
        "assumptions": [
            "No commissions, slippage, spread, taxes, CAD/USD conversion or Wealthsimple FX costs.",
            "If a session opens below the stop, exit is modeled at the open; otherwise at stop.",
            "Current-ticker history can begin after the requested horizon; a symbol only participates once enough bars exist for production indicators.",
            "Research branch only; production universe, portfolio state and notifications are unchanged.",
        ],
        "errors": errors,
    }
    Path("research/robust_candidate_results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Candidate Robustness Analysis — QBTS / IONQ / RGTI / MU",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "Indicators are recalculated from the latest <=180 bars on every historical date, matching the production scanner window.",
        "",
        "## New-symbol data coverage",
        "",
        "| Symbol | First bar | First signalable date | Last bar | Bars |",
        "|---|---|---|---|---:|",
    ]
    for s in NEW:
        c = coverage[s]
        lines.append(f"| {s} | {c['first_bar']} | {c['first_signalable']} | {c['last_bar']} | {c['bars']} |")

    for label in ["2y", "3y", "4y", "5y"]:
        rows = horizon_results[label]
        lines += ["", f"## {label.upper()} portfolio attribution", "",
                  "| Variant | Final equity | Return | Max DD | Trades | Win rate |",
                  "|---|---:|---:|---:|---:|---:|"]
        for r in rows:
            lines.append(
                f"| {r['name']} | C${r['final_equity_cad']:.2f} | {r['return_pct']:.2f}% | "
                f"{r['max_drawdown_pct']:.2f}% | {r['closed_trades']} | {r['win_rate_pct']}% |"
            )

    lines += ["", "## Six-month stability", ""]
    for block in block_results:
        lines += [f"### {block['start']} to {block['end']}", "",
                  "| Variant | Return | Max DD |",
                  "|---|---:|---:|"]
        for r in block["variants"]:
            lines.append(f"| {r['name']} | {r['return_pct']:.2f}% | {r['max_drawdown_pct']:.2f}% |")
        lines.append("")

    lines += ["## Walk-forward selection", "",
              "Winner is selected using only the prior six-month block, then tested on the next block.", "",
              "| Train | Test | Chosen | Train return | Test return | Test baseline | Test all-4 |",
              "|---|---|---|---:|---:|---:|---:|"]
    for w in walk_forward:
        lines.append(
            f"| {w['train']} | {w['test']} | {w['chosen_variant']} | {w['train_return_pct']:.2f}% | "
            f"{w['test_return_pct']:.2f}% | {w['test_baseline_return_pct']:.2f}% | {w['test_all4_return_pct']:.2f}% |"
        )

    lines += ["", "## Assumptions", ""] + [f"- {x}" for x in payload["assumptions"]]
    Path("research/robust_candidate_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote robust candidate analysis results", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
