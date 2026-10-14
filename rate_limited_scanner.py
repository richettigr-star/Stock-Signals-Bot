#!/usr/bin/env python3
"""Run the stock scanner with conservative Twelve Data request pacing.

The Basic Twelve Data plan allows 8 API credits per minute and /time_series
costs 1 credit per symbol. The scanner covers 20 symbols, so requests are
paced below that ceiling. If Twelve Data still returns HTTP 429 (for example
because another workflow used the same key), this wrapper waits for the quota
window to reset and retries without exposing the API key in logs.
"""

from __future__ import annotations

import time

import scanner

# ~6.3 requests/minute, leaving headroom below an 8-credit/minute plan.
MIN_REQUEST_INTERVAL_SECONDS = 9.5
RATE_LIMIT_COOLDOWN_SECONDS = 65
MAX_RATE_LIMIT_RETRIES = 3

_original_get = scanner.requests.get
_last_request_started: float | None = None


def _wait_for_pacing() -> None:
    global _last_request_started

    now = time.monotonic()
    if _last_request_started is not None:
        wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_started)
        if wait > 0:
            print(f"Rate limiter: waiting {wait:.1f}s before market-data request")
            time.sleep(wait)

    _last_request_started = time.monotonic()


def _redact_error_url(response):
    """Prevent requests exceptions from embedding the API key in logs/reports."""
    if response.status_code >= 400:
        response.url = scanner.API_URL
    return response


def paced_get(*args, **kwargs):
    """Pace every GET and recover from Twelve Data HTTP 429 responses."""
    global _last_request_started

    for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 1):
        _wait_for_pacing()
        response = _original_get(*args, **kwargs)

        if response.status_code != 429:
            return _redact_error_url(response)

        if attempt >= MAX_RATE_LIMIT_RETRIES:
            return _redact_error_url(response)

        print(
            "Rate limiter: Twelve Data returned HTTP 429; "
            f"waiting {RATE_LIMIT_COOLDOWN_SECONDS}s for quota reset "
            f"(retry {attempt}/{MAX_RATE_LIMIT_RETRIES - 1})"
        )
        time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
        _last_request_started = None

    raise RuntimeError("Unexpected rate limiter state")


scanner.requests.get = paced_get

if __name__ == "__main__":
    raise SystemExit(scanner.main())
