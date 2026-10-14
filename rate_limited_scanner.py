#!/usr/bin/env python3
"""Run the nightly scanner with conservative Twelve Data request pacing.

The scanner queries 20 symbols. Sending those requests back-to-back can exceed
Twelve Data's per-minute API allowance and produce HTTP 429 responses. This
wrapper spaces every HTTP GET (including retries) so the scan remains below a
conservative ~7 requests/minute.
"""

from __future__ import annotations

import sys
import time

import scanner

MIN_REQUEST_INTERVAL_SECONDS = 8.5
_original_get = scanner.requests.get
_last_request_started: float | None = None


def paced_get(*args, **kwargs):
    global _last_request_started

    now = time.monotonic()
    if _last_request_started is not None:
        wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_started)
        if wait > 0:
            print(f"Rate limiter: waiting {wait:.1f}s before Twelve Data request")
            time.sleep(wait)

    _last_request_started = time.monotonic()
    return _original_get(*args, **kwargs)


scanner.requests.get = paced_get

if __name__ == "__main__":
    raise SystemExit(scanner.main())
