#!/usr/bin/env python3
"""Exact-production-window wrapper for the isolated candidate backtest.

Production scanner.py requests OUTPUTSIZE=180 and computes EMA100/ATR14 over that
180-bar response. For each historical date, this wrapper recreates that same
trailing-180-bar indicator window before running the research backtest.
"""
from datetime import timedelta

import quantum_backtest as qb

PRODUCTION_OUTPUTSIZE = 180
qb.WARMUP_START = qb.START_DATE - timedelta(days=420)


def add_indicators_exact(rows):
    out = []
    min_required = max(qb.EMA_PERIOD + 10, qb.MOMENTUM_LOOKBACK + 1, qb.ATR_PERIOD + 1)
    for i, r in enumerate(rows):
        rr = dict(r)
        start = max(0, i - PRODUCTION_OUTPUTSIZE + 1)
        window = rows[start : i + 1]
        if len(window) < min_required:
            rr.update(
                ema100=None,
                atr14=None,
                momentum10=None,
                score=None,
                eligible=False,
                signal_stop=None,
                stop_pct=None,
            )
            out.append(rr)
            continue

        closes = [x["close"] for x in window]
        highs = [x["high"] for x in window]
        lows = [x["low"] for x in window]
        ema100 = qb.ema(closes, qb.EMA_PERIOD)[-1]
        atr14 = qb.wilder_atr(highs, lows, closes, qb.ATR_PERIOD)[-1]
        close = r["close"]
        mom = close / closes[-1 - qb.MOMENTUM_LOOKBACK] - 1.0

        rr["ema100"] = ema100
        rr["atr14"] = atr14
        if atr14 is None or close <= 0 or atr14 <= 0:
            rr.update(momentum10=None, score=None, eligible=False, signal_stop=None, stop_pct=None)
        else:
            atr_pct = float(atr14) / close
            rr["momentum10"] = mom
            rr["score"] = mom / atr_pct if atr_pct > 0 else float("-inf")
            rr["eligible"] = mom > qb.MOMENTUM_THRESHOLD and close > ema100
            rr["signal_stop"] = close - qb.ATR_MULTIPLIER * float(atr14)
            rr["stop_pct"] = (qb.ATR_MULTIPLIER * float(atr14)) / close
        out.append(rr)
    return out


qb.add_indicators = add_indicators_exact

if __name__ == "__main__":
    raise SystemExit(qb.main())
