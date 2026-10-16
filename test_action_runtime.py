"""Clock-controlled scheduling, persistence and effective-observation regressions."""
import contextlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import action_runtime as runtime
import common
import intraday_exit
import verify_cadence
import build_dashboard
import deliver_pending
from test_monitor import Base, bars

NOW = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)
BOUNDS = (datetime(2026, 10, 16, 13, 30, tzinfo=timezone.utc),
          datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc))


class Clock:
    def __init__(self, now=NOW):
        self.started = now
        self.elapsed = 0

    def now(self):
        return self.started + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


class SessionTests(unittest.TestCase):
    def run_session(self, clock, cycle, duration=901, mode="monitor", store=None, handover=None):
        with patch.object(runtime, "session_bounds", return_value=BOUNDS):
            return runtime.run_session(mode, duration, clock=clock.now, monotonic=clock.monotonic,
                sleep=clock.sleep, cycle=cycle, store=store or Mock(sync=lambda: False),
                handover=handover or Mock(return_value=True))

    def test_reads_are_five_minutes_apart_without_processing_drift(self):
        clock = Clock()
        observed = []
        def cycle(store):
            observed.append(clock.elapsed)
            clock.sleep(23)
            return True
        self.assertEqual(self.run_session(clock, cycle), 0)
        self.assertEqual(observed, [0, 300, 600, 900])

    def test_failed_reading_does_not_cancel_later_scans(self):
        clock = Clock()
        observed = []
        def cycle(store):
            observed.append(clock.elapsed)
            return len(observed) != 1
        self.assertEqual(self.run_session(clock, cycle), 1)
        self.assertEqual(observed, [0, 300, 600, 900])

    def test_overrun_skips_missed_slots_without_request_burst(self):
        clock = Clock()
        observed = []
        def cycle(store):
            observed.append(clock.elapsed)
            clock.sleep(310)
            return True
        self.run_session(clock, cycle)
        self.assertEqual(observed, [0, 600])

    def test_handover_is_requested_before_budget_and_only_once(self):
        clock = Clock()
        handover = Mock(return_value=True)
        self.run_session(clock, lambda store: True, duration=1200, handover=handover)
        handover.assert_called_once_with("intraday-exits.yml")

    def test_handover_failure_is_retried_and_job_is_not_green(self):
        handover = Mock(return_value=False)
        self.assertEqual(self.run_session(Clock(), lambda store: True, handover=handover), 1)
        self.assertGreater(handover.call_count, 1)

    def test_checkpoint_failure_stops_worker_and_requests_recovery(self):
        handover = Mock(return_value=True)
        cycle = Mock(side_effect=RuntimeError("private-token"))
        self.assertEqual(self.run_session(Clock(), cycle, duration=1200, handover=handover), 1)
        cycle.assert_called_once()
        handover.assert_called_once_with("intraday-exits.yml")

    def test_new_code_yields_before_another_scan(self):
        cycle = Mock()
        self.assertEqual(self.run_session(Clock(), cycle, store=Mock(sync=lambda: True)), 1)
        cycle.assert_not_called()

    def test_watchdog_checks_every_minute(self):
        clock = Clock()
        observed = []
        self.run_session(clock, lambda store: observed.append(clock.elapsed) or True,
                         duration=181, mode="watchdog")
        self.assertEqual(observed, [0, 60, 120, 180])

    def test_watchdog_recovered_failure_finishes_green_without_stopping_checks(self):
        clock = Clock()
        observed = []
        def cycle(store):
            observed.append(clock.elapsed)
            return len(observed) != 1
        self.assertEqual(self.run_session(clock, cycle, duration=181, mode="watchdog"), 0)
        self.assertEqual(observed, [0, 60, 120, 180])

    def test_watchdog_persistent_failure_finishes_red(self):
        self.assertEqual(self.run_session(Clock(), lambda store: False,
                         duration=181, mode="watchdog"), 1)

    def test_watchdog_relapse_after_recovery_finishes_red(self):
        cycle = Mock(side_effect=[False, True, True, False])
        self.assertEqual(self.run_session(Clock(), cycle, duration=181, mode="watchdog"), 1)
        self.assertEqual(cycle.call_count, 4)

    def test_watchdog_healthy_then_final_failure_finishes_red(self):
        cycle = Mock(side_effect=[True, True, True, False])
        self.assertEqual(self.run_session(Clock(), cycle, duration=181, mode="watchdog"), 1)

    def test_watchdog_recovery_cannot_hide_handover_failure(self):
        cycle = Mock(side_effect=[False, True, True, True])
        self.assertEqual(self.run_session(Clock(), cycle, duration=181, mode="watchdog",
                         handover=Mock(return_value=False)), 1)

    def test_watchdog_recovery_cannot_hide_checkpoint_failure(self):
        cycle = Mock(side_effect=[False, True, RuntimeError("private-token")])
        self.assertEqual(self.run_session(Clock(), cycle, duration=181, mode="watchdog"), 1)

    def test_watchdog_no_checks_cannot_claim_recovery(self):
        clock = Clock(BOUNDS[0] - timedelta(minutes=3))
        cycle = Mock()
        self.assertEqual(self.run_session(clock, cycle, duration=1, mode="watchdog"), 1)
        cycle.assert_not_called()

    def test_opening_waits_for_first_minute_bar(self):
        clock = Clock(BOUNDS[0] - timedelta(minutes=3))
        observed = []
        self.run_session(clock, lambda store: observed.append(clock.now()) or True, duration=241)
        self.assertEqual(observed, [BOUNDS[0] + timedelta(minutes=1)])

    def test_holiday_does_not_fetch_quotes_or_dispatch(self):
        cycle, handover = Mock(), Mock()
        with patch.object(runtime, "session_bounds", return_value=None):
            self.assertEqual(runtime.run_session("monitor", clock=lambda: NOW,
                             cycle=cycle, handover=handover), 0)
        cycle.assert_not_called()
        handover.assert_not_called()

    def test_early_close_stops_and_does_not_dispatch(self):
        clock = Clock(BOUNDS[1] + timedelta(minutes=20, seconds=1))
        cycle, handover = Mock(), Mock()
        self.assertEqual(self.run_session(clock, cycle, handover=handover), 0)
        cycle.assert_not_called()
        handover.assert_not_called()


def sample(offset, *, effective=True, quote_offset=0):
    stamp = NOW + timedelta(seconds=offset)
    return {"completed_at_utc": stamp.isoformat(), "effective": effective,
            "symbols": {"COST": {"status": "ok", "confirmed": True, "bar_age_seconds": 60,
                "bar_at_utc": (stamp - timedelta(seconds=60 + quote_offset)).isoformat()}}}


class CadenceTests(unittest.TestCase):
    def assess(self, samples, now=NOW + timedelta(seconds=600)):
        return verify_cadence.assess({"samples": samples}, now)

    def test_three_fresh_advancing_readings_establish_only_observed_window(self):
        result = self.assess([sample(0), sample(300), sample(600)])
        self.assertEqual(result["status"], "observed_window_pass")
        self.assertIn("Recorded window only", result["scope"])

    def test_repeated_quote_is_not_effective_cadence(self):
        result = self.assess([sample(0), sample(300, quote_offset=300), sample(600)])
        self.assertEqual(result["status"], "unverified_or_degraded")
        self.assertEqual(result["failed_or_repeated_readings"], 1)

    def test_three_rapid_runs_do_not_prove_ten_minutes_of_cadence(self):
        result = self.assess([sample(0), sample(60), sample(120)], NOW + timedelta(seconds=120))
        self.assertEqual(result["status"], "unverified_or_degraded")
        self.assertEqual(result["effective_streak_span_seconds"], 120)

    def test_successful_jobs_with_old_quotes_do_not_pass(self):
        samples = [sample(0), sample(300), sample(600)]
        samples[-1]["symbols"]["COST"]["bar_age_seconds"] = 240
        self.assertEqual(self.assess(samples)["status"], "unverified_or_degraded")

    def test_gap_cannot_be_hidden_by_later_good_streak(self):
        samples = [sample(offset) for offset in (0, 900, 1200, 1500)]
        result = self.assess(samples, NOW + timedelta(seconds=1500))
        self.assertEqual(result["status"], "unverified_or_degraded")
        self.assertEqual(result["gaps_over_target_seconds"], [900])

    def test_failed_reading_remains_visible_after_recovery(self):
        samples = [sample(0, effective=False)] + [sample(offset) for offset in (300, 600, 900)]
        self.assertEqual(self.assess(samples, NOW + timedelta(seconds=900))["status"],
                         "unverified_or_degraded")

    def test_saved_success_expires_when_monitor_stops(self):
        result = self.assess([sample(0), sample(300), sample(600)], NOW + timedelta(seconds=1000))
        self.assertEqual(result["status"], "unverified_or_degraded")

    def test_no_holdings_no_quotes_cannot_claim_effective_readings(self):
        self.assertEqual(self.assess([{"completed_at_utc": NOW.isoformat(), "effective": True,
                                      "symbols": {}}])["status"], "unverified_or_degraded")

    def test_post_close_repeated_bars_do_not_invalidate_regular_session_evidence(self):
        close = BOUNDS[1]
        samples = [sample(int((close - NOW).total_seconds()) + offset) for offset in (-660, -360, -60, 240)]
        result = self.assess(samples, close + timedelta(minutes=10))
        self.assertEqual(result["status"], "observed_window_pass")
        self.assertEqual(result["samples"], 3)


class OutboxCrashTests(Base):
    def test_exit_is_durable_before_position_is_removed(self):
        original_save = common.save_json
        def save(path, payload):
            if path == "signal_state.json":
                raise OSError("simulated disk failure")
            original_save(path, payload)
        with patch.object(intraday_exit, "fetch_today_minute_bars", return_value=bars(True)), \
             patch.object(intraday_exit, "save_json", side_effect=save):
            self.assertEqual(intraday_exit.run(defer_notifications=True), 1)
        self.assertIn("COST", common.load_json("signal_state.json")["positions"])
        self.assertEqual(common.load_json("signal_events.json")["events"][0]["type"], "EXIT")
        self.post.assert_not_called()
        self.assertEqual(self.run_monitor(bars(True)), 0)
        exits = [event for event in common.load_json("signal_events.json")["events"]
                 if event["type"] == "EXIT"]
        self.assertEqual(len(exits), 1)


class CompleteCycleTests(Base):
    def run_cycle(self, crossed=False):
        checkpoints = []
        def checkpoint(files=None):
            checkpoints.append(common.load_json("signal_events.json"))
        def command(script, *arguments, **kwargs):
            if script == "intraday_exit.py":
                return intraday_exit.run(defer_notifications=True)
            if script == "deliver_pending.py":
                return deliver_pending.main()
            if script == "build_dashboard.py":
                build_dashboard.main()
                return 0
            raise AssertionError(script)
        with patch.object(runtime, "command", side_effect=command), \
             patch.object(intraday_exit, "fetch_today_minute_bars", return_value=bars(crossed)):
            result = runtime.monitor_cycle(Mock(checkpoint=checkpoint))
        return result, checkpoints

    def test_full_cycle_keeps_position_and_records_fresh_observation(self):
        state = common.load_json("signal_state.json")
        state["positions"]["COST"].update(stop_usd=946.711, initial_stop_usd=946.711)
        common.save_json("signal_state.json", state)
        result, checkpoints = self.run_cycle()
        self.assertTrue(result)
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(common.load_json("signal_state.json")["positions"]["COST"]["stop_usd"], 946.711)
        self.assertTrue(common.load_json("monitor_cadence.json")["samples"][0]["effective"])
        self.post.assert_not_called()

    def test_full_exit_cycle_checkpoints_before_send_and_does_not_replay(self):
        result, checkpoints = self.run_cycle(crossed=True)
        self.assertTrue(result)
        self.assertEqual(checkpoints[0]["events"][0]["telegram_alert_status"], "pending")
        self.assertEqual(checkpoints[1]["events"][0]["telegram_alert_status"], "sent")
        self.assertEqual(self.post.call_count, 1)
        self.run_cycle(crossed=True)
        self.assertEqual(self.post.call_count, 1)

    def test_full_cycle_reports_telegram_rejection_as_degraded(self):
        self.post.return_value = Mock(status_code=200, json=lambda: {"ok": False})
        result, checkpoints = self.run_cycle(crossed=True)
        self.assertFalse(result)
        self.assertEqual(common.load_json("monitor_health.json")["status"], "degraded")
        self.assertFalse(common.load_json("monitor_cadence.json")["samples"][0]["effective"])
        self.assertEqual(checkpoints[-1]["events"][0]["telegram_alert_status"], "failed")


class CheckpointTests(unittest.TestCase):
    def test_remote_trading_state_change_is_not_rebased_or_overwritten(self):
        store = runtime.GitStore(runtime.MONITOR_FILES)
        def git(*arguments):
            if arguments[0] == "push":
                raise RuntimeError("rejected")
            if arguments[:2] == ("merge-base", "HEAD"):
                return "base"
            if arguments[:3] == ("diff", "--name-only", "base"):
                return "signal_state.json"
            return ""
        with patch.object(store, "git", side_effect=git) as calls:
            with self.assertRaisesRegex(RuntimeError, "Concurrent trading state"):
                store.checkpoint()
        self.assertFalse(any(call.args[0] == "rebase" for call in calls.call_args_list))

    def test_unrelated_watchdog_commit_can_be_rebased_before_retrying_push(self):
        store = runtime.GitStore(runtime.MONITOR_FILES)
        pushes = []
        def git(*arguments):
            if arguments[0] == "push":
                pushes.append(arguments)
                if len(pushes) == 1:
                    raise RuntimeError("rejected")
            if arguments[:2] == ("merge-base", "HEAD"):
                return "base"
            if arguments[:3] == ("diff", "--name-only", "base"):
                return "watchdog_health.json"
            return ""
        with patch.object(store, "git", side_effect=git) as calls, patch.object(runtime.time, "sleep"):
            store.checkpoint()
        self.assertEqual(len(pushes), 2)
        self.assertTrue(any(call.args[0] == "rebase" for call in calls.call_args_list))

    def test_no_notification_send_when_durable_checkpoint_fails(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            previous = os.getcwd()
            os.chdir(directory)
            stack.callback(os.chdir, previous)
            common.save_json("signal_events.json", {"events": [{"type": "EXIT", "telegram_alert_status": "pending"}]})
            stack.enter_context(patch.object(runtime, "command", return_value=0))
            store = Mock(checkpoint=Mock(side_effect=RuntimeError("storage unavailable")))
            with self.assertRaises(RuntimeError):
                runtime.monitor_cycle(store)
            runtime.command.assert_called_once_with("intraday_exit.py", "--defer-notifications")

    def test_dispatch_rejects_unexpected_destination_without_sending_token(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "someone/else", "GH_TOKEN": "private"}), \
             patch.object(runtime.requests, "post") as post:
            self.assertFalse(runtime.dispatch("intraday-exits.yml"))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
