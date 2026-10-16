"""Reliability regressions for the intraday monitor and watchdog."""
import contextlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import common
import intraday_exit as monitor
import monitor_watchdog as watchdog
import notifications

NOW = datetime(2026, 10, 16, 14, 20, tzinfo=timezone.utc)


class Timestamp:
    def __init__(self, value): self.value = value
    def to_pydatetime(self): return self.value


class FakeCalendar:
    def is_session(self, day):
        return datetime.fromisoformat(str(day)[:10]).weekday() < 5
    def session_open(self, day):
        return Timestamp(datetime.fromisoformat(str(day)[:10] + "T09:30:00").replace(tzinfo=common.NY))
    def session_close(self, day):
        return Timestamp(datetime.fromisoformat(str(day)[:10] + "T16:00:00").replace(tzinfo=common.NY))
    def date_to_session(self, day, direction="next"):
        value = datetime.fromisoformat(str(day)[:10])
        while not self.is_session(value.date()):
            value += timedelta(days=1)
        return value.date().isoformat()


def portfolio():
    return {"holdings": {"COST": {"status": "active", "entry_date": "2026-10-15",
                                    "entry_price_usd": 985.4, "invested_cad": 33.33}}}


def fresh_health():
    return {"completed_at_utc": (NOW - timedelta(minutes=4)).isoformat(), "status": "ok",
            "notifications_ok": True,
            "symbols": {"COST": {"status": "ok", "holding_confirmed": True,
                                 "checked_at_utc": (NOW - timedelta(minutes=4)).isoformat()}}}


class WatchdogTests(unittest.TestCase):
    def bounds(self):
        return (datetime(2026, 10, 16, 13, 30, tzinfo=timezone.utc),
                datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc))

    def test_fresh_monitor_is_ok(self):
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            self.assertEqual(watchdog.assess(NOW, fresh_health(), portfolio()), ("ok", []))

    def test_stale_monitor_is_detected(self):
        health = fresh_health()
        health["completed_at_utc"] = (NOW - timedelta(minutes=20)).isoformat()
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            status, problems = watchdog.assess(NOW, health, portfolio())
        self.assertEqual(status, "degraded")
        self.assertTrue(any("atrasado" in item for item in problems))

    def test_missing_symbol_health_is_detected(self):
        health = fresh_health()
        health["symbols"] = {}
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            status, problems = watchdog.assess(NOW, health, portfolio())
        self.assertEqual(status, "degraded")
        self.assertIn("COST: sem leitura recente", problems)

    def test_degraded_monitor_is_detected_even_with_fresh_heartbeat(self):
        health = fresh_health()
        health["status"] = "degraded"
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            status, problems = watchdog.assess(NOW, health, portfolio())
        self.assertEqual(status, "degraded")
        self.assertIn("monitor status=degraded", problems)

    def test_opening_grace_does_not_false_alarm(self):
        just_opened = datetime(2026, 10, 16, 13, 35, tzinfo=timezone.utc)
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            self.assertEqual(watchdog.assess(just_opened, {}, portfolio()), ("opening_grace", []))

    def test_outside_session_does_not_false_alarm(self):
        early = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            self.assertEqual(watchdog.assess(early, {}, portfolio()), ("outside_session", []))

    def test_fresh_heartbeat_does_not_hide_stale_symbol_reading(self):
        health = fresh_health()
        health["symbols"]["COST"]["checked_at_utc"] = (NOW - timedelta(minutes=8)).isoformat()
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            self.assertEqual(watchdog.assess(NOW, health, portfolio())[0], "degraded")

    def test_fresh_heartbeat_does_not_hide_failed_notifications(self):
        health = fresh_health()
        health["notifications_ok"] = False
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            self.assertEqual(watchdog.assess(NOW, health, portfolio())[0], "degraded")

    def test_invalid_heartbeat_timestamp_alerts_instead_of_crashing(self):
        health = fresh_health()
        health["completed_at_utc"] = "invalid"
        with patch.object(watchdog, "session_bounds", return_value=self.bounds()):
            self.assertEqual(watchdog.assess(NOW, health, portfolio())[0], "degraded")


class MonitorScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.dict(os.environ, {"TWELVE_DATA_API_KEY": "fake",
            "TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "123"}))
        self.stack.enter_context(patch.object(common, "calendar", return_value=FakeCalendar()))
        for module in (common, monitor, notifications):
            self.stack.enter_context(patch.object(module, "now_utc", return_value=NOW))
        common.save_json("signal_state.json", {"positions": {
            "COST": {"symbol": "COST", "status": "active", "signal_id": "ENTRY-COST-2026-10-14",
                     "signal_date": "2026-10-14", "stop_usd": 946.711, "initial_stop_usd": 946.711,
                     "last_stop_update_date": "2026-10-15",
                     "last_checked_bar_utc": "2026-10-16T13:30:00+00:00"},
            "WMT": {"symbol": "WMT", "status": "pending_entry", "signal_id": "ENTRY-WMT-2026-10-15",
                    "signal_date": "2026-10-15", "stop_usd": 111.5489, "initial_stop_usd": 111.5489,
                    "last_stop_update_date": "2026-10-15"},
            "UNH": {"symbol": "UNH", "status": "pending_entry", "signal_id": "ENTRY-UNH-2026-10-15",
                    "signal_date": "2026-10-15", "stop_usd": 377.4134, "initial_stop_usd": 377.4134,
                    "last_stop_update_date": "2026-10-15"}}, "closed_signals": []})
        common.save_json("portfolio_state.json", portfolio())
        common.save_json("signal_events.json", {"events": []})

    def tearDown(self):
        self.stack.close()
        os.chdir(self.old)
        self.tmp.cleanup()

    def minute_bars(self):
        start = datetime(2026, 10, 16, 9, 30)
        return [{"datetime": (start + timedelta(minutes=i)).isoformat(sep=" "),
                 "open": 980.0, "high": 982.0, "low": 970.0, "close": 981.0}
                for i in range(50)]

    def test_only_confirmed_cost_is_queried(self):
        queried = []
        def fake_fetch(symbol, api_key):
            queried.append(symbol)
            return self.minute_bars()
        with patch.object(monitor, "fetch_today_minute_bars", side_effect=fake_fetch):
            self.assertEqual(monitor.run(), 0)
        self.assertEqual(queried, ["COST"])
        health = common.load_json("monitor_health.json")
        self.assertEqual(health["active_holdings"], ["COST"])
        self.assertEqual(health["unconfirmed_signals_skipped"], ["UNH", "WMT"])

    def test_cost_stop_reference_is_fill_based_value(self):
        state = common.load_json("signal_state.json")
        pos = state["positions"]["COST"]
        self.assertEqual(pos["initial_stop_usd"], 946.711)
        self.assertEqual(monitor.applicable_stop(pos, NOW), 946.711)


class WorkflowConfigTests(unittest.TestCase):
    def workflow_text(self):
        return Path(".github/workflows/intraday-exits.yml").read_text(encoding="utf-8")

    def test_schedules_are_recovery_triggers_with_new_york_timezone(self):
        text = self.workflow_text()
        self.assertEqual(text.count('timezone: "America/New_York"'), 2)
        self.assertIn("python action_runtime.py monitor", text)
        self.assertNotIn("sleep 300", text)

    def test_monitor_and_daily_share_non_cancelling_queue(self):
        text = self.workflow_text()
        daily = Path(".github/workflows/daily-signals.yml").read_text()
        for config in (text, daily):
            self.assertIn("group: stock-signal-state", config)
            self.assertIn("cancel-in-progress: false", config)
            self.assertIn("queue: max", config)

    def test_watchdog_runs_without_the_trading_state_lock(self):
        text = Path(".github/workflows/monitor-watchdog.yml").read_text()
        self.assertIn("group: stock-monitor-watchdog", text)
        self.assertNotIn("group: stock-signal-state", text)
        self.assertIn("python action_runtime.py watchdog", text)

    def test_intraday_ci_runs_all_regressions_and_has_room_for_handover(self):
        text = self.workflow_text()
        self.assertIn("python -m unittest -q", text)
        self.assertIn("timeout-minutes: 355", text)
        self.assertIn("actions: write", text)
        self.assertIn("actions/upload-artifact@v4", text)


if __name__ == "__main__":
    unittest.main()
