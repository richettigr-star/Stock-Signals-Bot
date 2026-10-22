"""Shared strict state IO, market calendar and data validation."""
import json
import math
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
def now_utc():
    return datetime.now(timezone.utc)
def utc_now():
    return now_utc().isoformat()
def parse_time(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed.astimezone(timezone.utc)
def load_json(path, default=None, required=False):
    path = Path(path)
    if not path.exists():
        if required:
            raise RuntimeError(f"Required state missing: {path.name}")
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return data
def save_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        output.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(tmp, path)
    if hasattr(os, "O_DIRECTORY"):
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
@lru_cache(maxsize=1)
def calendar():
    import exchange_calendars
    return exchange_calendars.get_calendar("XNYS", start="2020-01-01", end="2035-12-31")
def session_bounds(day):
    day = str(day)[:10]
    cal = calendar()
    if not cal.is_session(day):
        return None
    return (cal.session_open(day).to_pydatetime(), cal.session_close(day).to_pydatetime())
def next_open(signal_day):
    day = (datetime.fromisoformat(str(signal_day)[:10]).date() + timedelta(days=1)).isoformat()
    session = calendar().date_to_session(day, direction="next")
    return calendar().session_open(session).to_pydatetime()
def monitor_window(now):
    bounds = session_bounds(now.astimezone(NY).date())
    return bool(bounds and bounds[0] <= now <= bounds[1] + timedelta(minutes=20))
def completed_scan_day(now):
    day = now.astimezone(NY).date().isoformat()
    bounds = session_bounds(day)
    return day if bounds and now >= bounds[1] + timedelta(minutes=15) else None
def regular_bar(value):
    stamp = datetime.fromisoformat(value)
    stamp = stamp.replace(tzinfo=NY) if stamp.tzinfo is None else stamp
    bounds = session_bounds(stamp.astimezone(NY).date())
    return bool(bounds and bounds[0] <= stamp < bounds[1])
def validate_ohlc(row):
    vals = [float(row[k]) for k in ("open", "high", "low", "close")]
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("Invalid non-positive/non-finite market price")
    op, high, low, close = vals
    if high < max(op, low, close) or low > min(op, high, close):
        raise ValueError("Inconsistent OHLC prices")
def append_event(payload, event):
    events = payload.setdefault("events", [])
    if any(e.get("id") == event["id"] for e in events):
        return False
    events.append(event)
    # Never discard undelivered alerts to enforce a history-length cap.
    pending = [e for e in events if e.get("telegram_alert_status") not in {"sent", "skipped_stale", "skipped_superseded"}]
    terminal = [e for e in events if e not in pending][-500:]
    payload["events"] = sorted(terminal + pending, key=lambda e: e.get("created_at_utc", ""))
    payload["updated_at_utc"] = utc_now()
    return True
