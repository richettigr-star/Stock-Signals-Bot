"""Measure effective quote observations, not scheduled triggers or job success."""
import json
import os
from datetime import datetime, timezone

from common import NY, load_json, now_utc, parse_time, save_json, session_bounds


def record_sample(health, succeeded):
    payload = load_json("monitor_cadence.json", {"version": 1, "samples": []})
    symbols = {}
    for symbol, item in health.get("symbols", {}).items():
        stamp = item.get("bar_datetime_ny")
        if stamp:
            stamp = datetime.fromisoformat(stamp)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=NY)
        symbols[symbol] = {"bar_at_utc": stamp.astimezone(timezone.utc).isoformat() if stamp else None,
                           "status": item.get("status"),
                           "confirmed": item.get("holding_confirmed"),
                           "bar_age_seconds": item.get("bar_age_seconds")}
    payload["samples"].append({"started_at_utc": health.get("started_at_utc"),
        "completed_at_utc": health.get("completed_at_utc"), "run_id": os.getenv("GITHUB_RUN_ID"),
        "effective": bool(succeeded and health.get("status") == "ok" and symbols),
        "symbols": symbols})
    payload["samples"] = payload["samples"][-200:]
    save_json("monitor_cadence.json", payload)


def assess(payload, now):
    today = now.astimezone(NY).date()
    bounds = session_bounds(today)
    samples = [sample for sample in payload.get("samples", [])
               if sample.get("completed_at_utc") and
               parse_time(sample["completed_at_utc"]).astimezone(NY).date() == today and
               bounds and bounds[0] <= parse_time(sample["completed_at_utc"]) <= bounds[1]]
    streak = 0
    longest = 0
    previous = None
    streak_started = None
    previous_bars = {}
    gaps = []
    failures = 0
    for sample in samples:
        completed = parse_time(sample["completed_at_utc"])
        symbols = sample.get("symbols", {})
        bars = {symbol: parse_time(item.get("bar_at_utc")) for symbol, item in symbols.items()
                if item.get("confirmed") is True}
        valid = bool(sample.get("effective") and bars and all(
            item.get("status") == "ok" and item.get("bar_age_seconds") is not None and
            0 <= item["bar_age_seconds"] <= 180 for item in symbols.values()))
        if previous:
            gap = (completed - previous).total_seconds()
            if gap > 360 or gap <= 0:
                gaps.append(round(gap, 3))
                streak = 0
                streak_started = None
            if set(bars) != set(previous_bars):
                streak = 0
                streak_started = None
            elif any(stamp is None or previous_bars[symbol] is None or stamp <= previous_bars[symbol]
                     for symbol, stamp in bars.items()):
                valid = False
        if valid:
            if streak_started is None:
                streak_started = completed
            streak += 1
            longest = max(longest, streak)
        else:
            failures += 1
            streak = 0
            streak_started = None
        previous, previous_bars = completed, bars
    age = (min(now, bounds[1]) - previous).total_seconds() if previous and bounds else None
    span = (previous - streak_started).total_seconds() if previous and streak_started else 0
    passed = streak >= 3 and span >= 540 and age is not None and 0 <= age <= 360 and not gaps and not failures
    return {"status": "observed_window_pass" if passed else "unverified_or_degraded",
            "date_ny": today.isoformat(), "samples": len(samples),
            "effective_streak": streak, "longest_effective_streak": longest,
            "effective_streak_span_seconds": round(span, 3),
            "failed_or_repeated_readings": failures, "gaps_over_target_seconds": gaps,
            "last_observation_age_seconds": round(age, 3) if age is not None else None,
            "scope": "Recorded window only; does not prove unattended session startup or future availability."}


if __name__ == "__main__":
    report = assess(load_json("monitor_cadence.json", {"samples": []}), now_utc())
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "observed_window_pass" else 1)
