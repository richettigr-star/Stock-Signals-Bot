"""Regression coverage for continuous supervision, safe bootstrap and runner handover."""
import contextlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import common
import session_supervisor as supervisor
from test_action_runtime import Clock

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
BOUNDS = (NOW.replace(hour=13, minute=30), NOW.replace(hour=20))


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        previous = os.getcwd()
        os.chdir(directory)
        self.stack.callback(os.chdir, previous)
        self.stack.enter_context(patch.object(supervisor, "session_bounds", return_value=BOUNDS))
        self.stack.enter_context(patch("monitor_watchdog.session_bounds", return_value=BOUNDS))
        self.sender = self.stack.enter_context(patch.object(supervisor, "send", return_value=True))
        common.save_json("portfolio_state.json", {"holdings": {"COST": {"status": "active"}}})
        common.save_json("signal_state.json", {"positions": {"COST": {"stop_usd": 947.974},
                         "WMT": {"status": "pending_entry"}, "UNH": {"status": "pending_entry"}}})
        self.store = Mock(sync=lambda: False)
        self.trigger = Mock(return_value=True)

    def healthy(self, now=NOW):
        common.save_json("monitor_health.json", {"status": "ok", "notifications_ok": True,
            "completed_at_utc": now.isoformat(), "symbols": {"COST": {
                "status": "ok", "holding_confirmed": True, "checked_at_utc": now.isoformat()}}})
        common.save_json("watchdog_health.json", {"status": "ok", "checked_at_utc": now.isoformat()})

    def cycle(self, now=NOW, runs=None):
        return supervisor.supervise_once(self.store, clock=lambda: now,
            list_runs=runs or Mock(return_value=[]), trigger=self.trigger)

    def test_missing_workers_are_requested_without_claiming_effective_readings(self):
        protected = {path: Path(path).read_bytes()
                     for path in ("portfolio_state.json", "signal_state.json")}
        self.assertFalse(self.cycle())
        self.assertEqual(self.trigger.call_count, 2)
        health = common.load_json(supervisor.HEALTH_FILE)
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["workflows"]["intraday-exits.yml"]["status"], "recovery_requested")
        self.assertFalse(Path("monitor_cadence.json").exists())
        for path, before in protected.items():
            self.assertEqual(Path(path).read_bytes(), before)

    def test_running_and_queued_workers_are_not_dispatched_again(self):
        self.healthy()
        runs = Mock(side_effect=[[{"status": "in_progress", "id": 1}], [{"status": "queued", "id": 2}]])
        self.assertTrue(self.cycle(runs=runs))
        self.trigger.assert_not_called()
        self.sender.assert_not_called()

    def test_requests_are_deduplicated_across_service_restarts(self):
        self.cycle()
        self.cycle(NOW + timedelta(minutes=1))
        self.assertEqual(self.trigger.call_count, 2)
        self.assertEqual(self.sender.call_count, 1)
        self.cycle(NOW + timedelta(minutes=15))
        self.assertEqual(self.trigger.call_count, 4)

    def test_failed_dispatch_cannot_be_reported_as_success(self):
        self.trigger.return_value = False
        self.assertFalse(self.cycle())
        health = common.load_json(supervisor.HEALTH_FILE)
        self.assertEqual(health["last_requests"], {})
        self.assertEqual(health["workflows"]["intraday-exits.yml"]["status"], "dispatch_failed")

    def test_unverifiable_api_does_not_trigger_duplicate_workers(self):
        self.assertFalse(self.cycle(runs=Mock(side_effect=RuntimeError("private-token"))))
        self.trigger.assert_not_called()
        self.assertNotIn("private-token", Path(supervisor.HEALTH_FILE).read_text())

    def test_premarket_bootstrap_starts_before_the_open_without_false_alert(self):
        self.assertFalse(self.cycle(BOUNDS[0] - timedelta(minutes=5)))
        self.assertEqual(self.trigger.call_count, 2)
        self.sender.assert_not_called()

    def test_outside_window_does_not_query_dispatch_or_alert(self):
        runs = Mock()
        self.assertTrue(self.cycle(BOUNDS[0] - timedelta(hours=3), runs=runs))
        runs.assert_not_called()
        self.trigger.assert_not_called()
        self.sender.assert_not_called()
        self.assertEqual(common.load_json(supervisor.HEALTH_FILE)["status"], "standby")

    def test_holiday_remains_running_without_starting_market_workers(self):
        with patch.object(supervisor, "session_bounds", return_value=None):
            self.assertTrue(self.cycle())
        self.trigger.assert_not_called()

    def test_stale_watchdog_alert_is_retried_after_telegram_rejection(self):
        self.sender.return_value = False
        self.cycle()
        self.cycle(NOW + timedelta(minutes=1))
        self.assertEqual(self.sender.call_count, 2)
        health = common.load_json(supervisor.HEALTH_FILE)
        self.assertFalse(health["notifications_ok"])
        self.assertIsNone(health["last_alert_bucket"])

    def test_actual_recovery_clears_current_problems_not_historical_requests(self):
        self.cycle()
        self.healthy()
        self.assertTrue(self.cycle(runs=Mock(return_value=[{"status": "in_progress", "id": 3}])))
        health = common.load_json(supervisor.HEALTH_FILE)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(len(health["last_requests"]), 2)

    def service(self, clock, cycle, duration=361, handover=None):
        return supervisor.run_supervisor(duration, clock=clock.now, monotonic=clock.monotonic,
            sleep=clock.sleep, store=self.store, cycle=cycle, handover=handover or self.trigger)

    def test_overnight_service_reaches_premarket_without_a_new_daily_trigger(self):
        clock = Clock(BOUNDS[0] - timedelta(minutes=12))
        observed = []
        result = self.service(clock, lambda store: observed.append(clock.elapsed) or True)
        self.assertEqual(result, 0)
        self.assertEqual(observed, [0, 300, 360])
        self.trigger.assert_called_once_with("session-supervisor.yml")

    def test_handover_failure_stays_red_even_if_last_cycle_is_healthy(self):
        self.assertEqual(self.service(Clock(NOW), lambda store: True,
                         handover=Mock(return_value=False)), 1)

    def test_code_changes_request_fresh_supervisor_before_another_cycle(self):
        self.store.sync = Mock(return_value=True)
        cycle = Mock()
        self.assertEqual(self.service(Clock(NOW), cycle, duration=1200), 0)
        cycle.assert_not_called()
        self.trigger.assert_called_once_with("session-supervisor.yml")

    def test_checkpoint_failure_stops_safely_and_requests_successor(self):
        cycle = Mock(side_effect=RuntimeError("private-token"))
        self.assertEqual(self.service(Clock(NOW), cycle, duration=1200), 1)
        cycle.assert_called_once()
        self.trigger.assert_called_once_with("session-supervisor.yml")


class SupervisorCalendarAndConfigTests(unittest.TestCase):
    def test_real_calendar_handles_dst_holiday_and_early_close(self):
        for stamp, expected in [
            ("2026-10-19T13:20:00+00:00", True),
            ("2026-11-02T13:20:00+00:00", False),
            ("2026-11-02T14:20:00+00:00", True),
            ("2026-11-26T15:00:00+00:00", False),
            ("2026-11-27T18:19:00+00:00", True),
            ("2026-11-27T18:21:00+00:00", False),
        ]:
            with self.subTest(stamp=stamp):
                self.assertEqual(supervisor.supervised_window(datetime.fromisoformat(stamp)), expected)

    def test_workflow_has_separate_lock_and_no_quote_credentials(self):
        workflow = Path(".github/workflows/session-supervisor.yml").read_text()
        self.assertIn("group: stock-session-supervisor", workflow)
        self.assertNotIn("group: stock-signal-state", workflow)
        self.assertNotIn("TWELVE_DATA_API_KEY", workflow)
        self.assertIn("timeout-minutes: 355", workflow)
        self.assertIn("python -m unittest -q", workflow)

    def test_invalid_destination_never_transmits_credentials(self):
        with patch.dict(os.environ, {"GH_TOKEN": "private", "GITHUB_REPOSITORY": "someone/else"}), \
             patch.object(supervisor.requests, "get") as get:
            with self.assertRaises(RuntimeError):
                supervisor.workflow_runs("intraday-exits.yml")
        get.assert_not_called()

    def test_invalid_api_response_is_fail_closed(self):
        with patch.dict(os.environ, {"GH_TOKEN": "private", "GITHUB_REPOSITORY": "richettigr-star/Stock-Signals-Bot"}), \
             patch.object(supervisor.requests, "get", return_value=Mock(json=lambda: {"workflow_runs": [{}]})):
            with self.assertRaises(RuntimeError):
                supervisor.workflow_runs("intraday-exits.yml")


if __name__ == "__main__":
    unittest.main()
