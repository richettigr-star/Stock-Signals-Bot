#!/usr/bin/env python3
"""
Nightly stock signal scanner for a fixed 20-stock universe.

Strategy:
- Daily bars
- Momentum10 > +2%
- Close > EMA100
- Rank = Momentum10 / (ATR14 / Close)
- ATR14 uses Wilder smoothing
- Initial/trailing distance reference = 2.5 * ATR14
- Long-only
- Up to 3 nightly entry candidates
- Intended execution: next US market open

This script DOES NOT place trades. It only writes signals.json and report.md.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API_URL = "https://api.twelvedata.com/time_series"

SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "TSLA", "AMD", "AVGO", "NFLX",
    "JPM", "BAC", "XOM", "CVX", "UNH",
    "LLY", "COST", "WMT", "PLTR", "COIN",
]

MOMENTUM_LOOKBACK = 10
MOMENTUM_THRESHOLD = 0.02
EMA_PERIOD = 100
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.5
MAX_CANDIDATES = 3
OUTPUTSIZE = 180

ACCOUNT_EQUITY_CAD = float(os.getenv("ACCOUNT_EQUITY_CAD", "100"))

RISK_PROFILES = {
    "LIVE Small": 0.075,
    "LIVE Small Aggressive": 0.08,
}

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 3


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
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
            prev_close = closes[i - 1]
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        trs.append(tr)

    atr: list[float | None] = [None] * len(trs)
    if len(trs) < period:
        return atr

    first_atr = sum(trs[:period]) / period
    atr[period - 1] = first_atr

    prev = first_atr
    for i in range(period, len(trs)):
        prev = ((prev * (period - 1)) + trs[i]) / period
        atr[i] = prev

    return atr


def fetch_symbol(symbol: str, api_key: str) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": OUTPUTSIZE,
        "adjust": "splits",
        "apikey": api_key,
    }

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "error":
                raise RuntimeError(
                    f"Twelve Data error for {symbol}: "
                    f"{data.get('code', '')} {data.get('message', 'unknown error')}"
                )

            values = data.get("values")
            if not values:
                raise RuntimeError(f"No daily data returned for {symbol}")

            rows = []
            for row in values:
                rows.append({
                    "date": row["datetime"][:10],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0),
                })

            rows.sort(key=lambda x: x["date"])
            return rows

        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP_SECONDS * attempt)

    raise RuntimeError(f"Failed to fetch {symbol}: {last_error}")


def analyze_symbol(symbol: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    min_required = max(EMA_PERIOD + 10, MOMENTUM_LOOKBACK + 1, ATR_PERIOD + 1)
    if len(rows) < min_required:
        raise RuntimeError(
            f"{symbol}: only {len(rows)} bars returned; need at least {min_required}"
        )

    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]

    ema100 = ema(closes, EMA_PERIOD)
    atr14 = wilder_atr(highs, lows, closes, ATR_PERIOD)

    i = len(rows) - 1
    close = closes[i]
    momentum10 = close / closes[i - MOMENTUM_LOOKBACK] - 1.0
    atr = atr14[i]

    if atr is None or close <= 0 or atr <= 0:
        raise RuntimeError(f"{symbol}: invalid ATR/close values")

    atr_pct = atr / close
    score = momentum10 / atr_pct if atr_pct > 0 else float("-inf")
    eligible = momentum10 > MOMENTUM_THRESHOLD and close > ema100[i]

    stop_distance = ATR_MULTIPLIER * atr
    stop_pct = stop_distance / close

    sizing = {}
    for profile_name, risk_fraction in RISK_PROFILES.items():
        risk_cad = ACCOUNT_EQUITY_CAD * risk_fraction
        risk_based_position_cad = risk_cad / stop_pct if stop_pct > 0 else 0.0
        sizing[profile_name] = {
            "risk_fraction": round(risk_fraction, 4),
            "risk_target_cad": round(risk_cad, 2),
            "risk_based_position_cad": round(risk_based_position_cad, 2),
            "max_without_leverage_cad": round(ACCOUNT_EQUITY_CAD, 2),
            "cash_capped_position_cad": round(min(risk_based_position_cad, ACCOUNT_EQUITY_CAD), 2),
        }

    return {
        "symbol": symbol,
        "bar_date": rows[i]["date"],
        "close_usd": round(close, 4),
        "momentum10": round(momentum10, 6),
        "momentum10_pct": round(momentum10 * 100, 3),
        "ema100": round(ema100[i], 4),
        "atr14": round(atr, 4),
        "atr_pct": round(atr_pct * 100, 3),
        "score": round(score, 6),
        "eligible": eligible,
        "planned_entry": "next_market_open",
        "reference_stop_usd": round(close - stop_distance, 4),
        "reference_stop_distance_usd": round(stop_distance, 4),
        "reference_stop_pct": round(stop_pct * 100, 3),
        "sizing_cad": sizing,
    }


def write_outputs(results: list[dict[str, Any]], errors: list[str]) -> None:
    ranked = sorted(
        [r for r in results if r["eligible"]],
        key=lambda x: x["score"],
        reverse=True,
    )
    candidates = ranked[:MAX_CANDIDATES]

    bar_dates = sorted({r["bar_date"] for r in results})
    latest_bar_date = bar_dates[-1] if bar_dates else None

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_bar_date": latest_bar_date,
        "strategy": {
            "universe": SYMBOLS,
            "momentum_lookback": MOMENTUM_LOOKBACK,
            "momentum_threshold_pct": MOMENTUM_THRESHOLD * 100,
            "ema_period": EMA_PERIOD,
            "atr_period": ATR_PERIOD,
            "atr_method": "Wilder",
            "atr_multiplier": ATR_MULTIPLIER,
            "ranking": "momentum10 / (atr14 / close)",
            "max_candidates": MAX_CANDIDATES,
            "direction": "long_only",
            "leverage": "none",
            "entry_timing": "next_market_open",
        },
        "account_equity_cad": ACCOUNT_EQUITY_CAD,
        "risk_profiles": RISK_PROFILES,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "all_symbols": sorted(results, key=lambda x: x["symbol"]),
        "errors": errors,
        "important_note": (
            "This scanner produces nightly candidates only. It does not know your actual "
            "Wealthsimple fills, cash balance, or existing open positions unless you manage "
            "those separately. Position sizing is an estimate and must be capped by available cash."
        ),
    }

    Path("signals.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Stock Signals Bot — Daily Report",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Latest market bar: {latest_bar_date or 'N/A'}",
        f"Account reference: C${ACCOUNT_EQUITY_CAD:.2f}",
        "",
    ]

    if candidates:
        lines += [
            f"## {len(candidates)} candidate(s) for the next market open",
            "",
        ]
        for rank, c in enumerate(candidates, 1):
            lines += [
                f"### {rank}. {c['symbol']}",
                f"- Momentum10: {c['momentum10_pct']:.3f}%",
                f"- Close: US${c['close_usd']:.4f}",
                f"- EMA100: US${c['ema100']:.4f}",
                f"- ATR14 (Wilder): US${c['atr14']:.4f}",
                f"- Score: {c['score']:.6f}",
                f"- Entry: next market open",
                f"- Reference stop from signal close: US${c['reference_stop_usd']:.4f}",
                f"- Stop distance: {c['reference_stop_pct']:.3f}% (= 2.5×ATR)",
                "",
            ]
            for profile, sizing in c["sizing_cad"].items():
                lines += [
                    f"**{profile}**",
                    f"- Target risk: C${sizing['risk_target_cad']:.2f}",
                    f"- Risk-based position: C${sizing['risk_based_position_cad']:.2f}",
                    f"- Cash-capped position (no leverage): C${sizing['cash_capped_position_cad']:.2f}",
                    "",
                ]
    else:
        lines += [
            "## No new entry candidates",
            "",
            "None of the 20 stocks met both Momentum10 > 2% and Close > EMA100.",
            "",
        ]

    if errors:
        lines += [
            "## Data warnings",
            "",
        ]
        lines += [f"- {e}" for e in errors]
        lines.append("")

    lines += [
        "## Execution note",
        "",
        "The signal is calculated after the daily bar is complete. Intended entry is the next market open.",
        "The stop shown is a reference based on the signal close. After a real fill, the practical stop reference is fill price minus 2.5×ATR from the signal bar.",
        "",
        "This is a signal tool, not an automated broker connection.",
        "",
    ]

    Path("report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        print("ERROR: TWELVE_DATA_API_KEY environment variable is missing.", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for symbol in SYMBOLS:
        try:
            rows = fetch_symbol(symbol, api_key)
            result = analyze_symbol(symbol, rows)
            results.append(result)
            print(
                f"{symbol}: date={result['bar_date']} "
                f"mom10={result['momentum10_pct']:.2f}% "
                f"eligible={result['eligible']}"
            )
        except Exception as exc:
            msg = str(exc)
            errors.append(msg)
            print(f"WARNING: {msg}", file=sys.stderr)

    if not results:
        print("ERROR: no symbols were analyzed successfully.", file=sys.stderr)
        return 1

    write_outputs(results, errors)
    print("Wrote signals.json and report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
