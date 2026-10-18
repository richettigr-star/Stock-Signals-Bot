#!/usr/bin/env python3
"""Canonical robustness analysis gated to each candidate's actual public ticker start.

Imports the research engine from robust_candidate_analysis.py but removes synthetic /
predecessor-SPAC history before indicator calculation for QBTS, IONQ and RGTI.
Research only; does not touch production state.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import robust_candidate_analysis as base

ACTUAL_PUBLIC_START = {
    "QBTS": date(2022, 8, 8),
    "IONQ": date(2021, 10, 1),
    "RGTI": date(2022, 3, 2),
    # MU has long continuous public history; no gate needed.
}


def main() -> int:
    key = os.getenv("TWELVE_DATA_API_KEY")
    if not key:
        raise SystemExit("TWELVE_DATA_API_KEY missing")

    data = {}
    errors = []
    for i, symbol in enumerate(base.ALL):
        try:
            print(f"Fetching {symbol} ({i+1}/{len(base.ALL)})", flush=True)
            rows = base.fetch(symbol, key)
            if symbol in ACTUAL_PUBLIC_START:
                floor = ACTUAL_PUBLIC_START[symbol].isoformat()
                rows = [r for r in rows if r["date"] >= floor]
            data[symbol] = base.add_production_indicators(rows)
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
        if i + 1 < len(base.ALL):
            time.sleep(base.RATE_LIMIT_SLEEP)

    missing = [s for s in base.ALL if s not in data]
    if missing:
        raise SystemExit("Missing symbols: " + ", ".join(missing))

    horizons = {
        "2y": date(2024, 10, 18),
        "3y": date(2023, 10, 18),
        "4y": date(2022, 10, 18),
        "5y": date(2021, 10, 18),
    }
    horizon_results = {
        label: base.variant_table(data, start, base.END_DATE)
        for label, start in horizons.items()
    }

    blocks = base.six_month_blocks()
    block_results = []
    for start, end in blocks:
        block_results.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "variants": base.variant_table(data, start, end),
        })

    walk_forward = []
    for i in range(len(block_results) - 1):
        train = block_results[i]
        test = block_results[i + 1]
        chosen = max(train["variants"], key=lambda r: r["return_pct"])["name"]
        train_map = {r["name"]: r for r in train["variants"]}
        test_map = {r["name"]: r for r in test["variants"]}
        walk_forward.append({
            "train": f"{train['start']}..{train['end']}",
            "test": f"{test['start']}..{test['end']}",
            "chosen_variant": chosen,
            "train_return_pct": train_map[chosen]["return_pct"],
            "test_return_pct": test_map[chosen]["return_pct"],
            "test_baseline_return_pct": test_map["Baseline 20"]["return_pct"],
            "test_all4_return_pct": test_map["+ all 4"]["return_pct"],
        })

    coverage = {}
    for s in base.NEW:
        coverage[s] = {
            "actual_public_start": ACTUAL_PUBLIC_START.get(s).isoformat() if s in ACTUAL_PUBLIC_START else None,
            "first_used_bar": data[s][0]["date"] if data[s] else None,
            "first_signalable": base.signalable_date(data[s]),
            "last_bar": data[s][-1]["date"] if data[s] else None,
            "bars": len(data[s]),
        }

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical": True,
        "data_source": "Twelve Data daily OHLC, adjust=splits",
        "candidate_public_start_gates": {k: v.isoformat() for k, v in ACTUAL_PUBLIC_START.items()},
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
            "candidate_prelisting_history": "excluded before indicator calculation",
        },
        "coverage_new_symbols": coverage,
        "horizons": horizon_results,
        "six_month_blocks": block_results,
        "walk_forward": walk_forward,
        "assumptions": [
            "QBTS begins only on 2022-08-08; IONQ on 2021-10-01; RGTI on 2022-03-02.",
            "A candidate only becomes signalable after enough post-listing bars exist for the production indicator minimum.",
            "No commissions, slippage, spread, taxes, CAD/USD conversion or Wealthsimple FX costs.",
            "Gap below stop exits at the open; otherwise stop fill is modeled at the stop.",
            "Research branch only; production universe and LIVE state are unchanged.",
        ],
        "errors": errors,
    }
    Path("research/robust_candidate_results_gated.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Canonical Candidate Robustness Analysis — Listing-Date Gated",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "This is the canonical robustness report. Pre-public/SPAC-predecessor history for QBTS, IONQ and RGTI is excluded before indicators are calculated.",
        "",
        "## Candidate coverage",
        "",
        "| Symbol | Actual public start | First used bar | First signalable | Last bar | Bars |",
        "|---|---|---|---|---|---:|",
    ]
    for s in base.NEW:
        c = coverage[s]
        lines.append(
            f"| {s} | {c['actual_public_start'] or 'long-standing'} | {c['first_used_bar']} | "
            f"{c['first_signalable']} | {c['last_bar']} | {c['bars']} |"
        )

    for label in ["2y", "3y", "4y", "5y"]:
        lines += ["", f"## {label.upper()} portfolio attribution", "",
                  "| Variant | Final equity | Return | Max DD | Trades | Win rate |",
                  "|---|---:|---:|---:|---:|---:|"]
        for r in horizon_results[label]:
            lines.append(
                f"| {r['name']} | C${r['final_equity_cad']:.2f} | {r['return_pct']:.2f}% | "
                f"{r['max_drawdown_pct']:.2f}% | {r['closed_trades']} | {r['win_rate_pct']}% |"
            )

    lines += ["", "## Six-month stability", ""]
    for block in block_results:
        lines += [f"### {block['start']} to {block['end']}", "",
                  "| Variant | Return | Max DD |", "|---|---:|---:|"]
        for r in block["variants"]:
            lines.append(f"| {r['name']} | {r['return_pct']:.2f}% | {r['max_drawdown_pct']:.2f}% |")
        lines.append("")

    lines += ["## Walk-forward selection", "",
              "Winner is selected from only the prior six-month block and then tested on the next block.", "",
              "| Train | Test | Chosen | Train return | Test return | Baseline test | All-4 test |",
              "|---|---|---|---:|---:|---:|---:|"]
    for w in walk_forward:
        lines.append(
            f"| {w['train']} | {w['test']} | {w['chosen_variant']} | {w['train_return_pct']:.2f}% | "
            f"{w['test_return_pct']:.2f}% | {w['test_baseline_return_pct']:.2f}% | {w['test_all4_return_pct']:.2f}% |"
        )

    lines += ["", "## Assumptions", ""] + [f"- {x}" for x in payload["assumptions"]]
    Path("research/robust_candidate_results_gated.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote canonical gated robustness results", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
