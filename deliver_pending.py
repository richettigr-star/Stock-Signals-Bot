#!/usr/bin/env python3
"""Retry the notification outbox without changing strategy decisions."""
from common import load_json, save_json
from notifications import deliver


def main():
    events = load_json("signal_events.json", {"version": 1, "events": []})
    ok = deliver(events)
    save_json("signal_events.json", events)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
