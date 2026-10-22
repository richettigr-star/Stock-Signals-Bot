"""Offline service scheduling, encryption and durable receipt regressions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from deploy import secret_envelope, server_runtime
from deploy import cutover_actions
from test_monitor import Base, FakeCalendar
import common
import notifications


class ServerSchedulingTests(unittest.TestCase):
    def stamp(self, value):
        return datetime.fromisoformat(value).replace(tzinfo=common.NY)

    def test_open_slot_and_five_minute_alignment(self):
        with patch.object(common, "calendar", return_value=FakeCalendar()):
            self.assertIsNone(server_runtime.monitor_slot(self.stamp("2026-10-22T09:30:59")))
            self.assertEqual(server_runtime.monitor_slot(self.stamp("2026-10-22T09:31:00"))[1], 0)
            self.assertEqual(server_runtime.monitor_slot(self.stamp("2026-10-22T09:35:59"))[1], 0)
            self.assertEqual(server_runtime.monitor_slot(self.stamp("2026-10-22T09:36:00"))[1], 1)

    def test_weekend_and_holiday_never_monitor(self):
        with patch.object(common, "calendar", return_value=FakeCalendar()):
            for date in ("2026-10-24", "2026-11-26"):
                self.assertIsNone(server_runtime.monitor_slot(self.stamp(date + "T10:00:00")))

    def test_early_close_and_daily_dedup(self):
        with patch.object(common, "calendar", return_value=FakeCalendar()):
            self.assertIsNotNone(server_runtime.monitor_slot(self.stamp("2026-11-27T13:19:00")))
            self.assertIsNone(server_runtime.monitor_slot(self.stamp("2026-11-27T13:21:00")))
            self.assertFalse(server_runtime.daily_due(self.stamp("2026-11-27T13:16:00"), {}))
            self.assertTrue(server_runtime.daily_due(self.stamp("2026-11-27T13:21:00"), {}))
            self.assertFalse(server_runtime.daily_due(self.stamp("2026-11-27T13:21:00"),
                             {"bar_date": "2026-11-27", "scan_accepted": True}))

    def test_dst_uses_exchange_local_open(self):
        with patch.object(common, "calendar", return_value=FakeCalendar()):
            self.assertEqual(server_runtime.monitor_slot(datetime(2026, 10, 22, 13, 31, tzinfo=timezone.utc))[1], 0)
            self.assertEqual(server_runtime.monitor_slot(datetime(2026, 11, 2, 14, 31, tzinfo=timezone.utc))[1], 0)


class EnvelopeTests(unittest.TestCase):
    def test_roundtrip_tampering_and_wrong_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "private.pem"
            public = Path(temporary) / "public.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                            "-out", str(private)], check=True, capture_output=True)
            public.write_bytes(secret_envelope.openssl("pkey", "-in", str(private), "-pubout", data=b""))
            encrypted = secret_envelope.encrypt(b"test-only credentials", public)
            self.assertEqual(secret_envelope.decrypt(encrypted, private), b"test-only credentials")
            encrypted["mac"] = "0" * 64
            with self.assertRaises(ValueError):
                secret_envelope.decrypt(encrypted, private)
            with self.assertRaises(subprocess.CalledProcessError):
                secret_envelope.decrypt(encrypted, public)

    def test_environment_rejects_missing_or_multiline(self):
        values = {name: "test" for name in ("TWELVE_DATA_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
        self.assertIn('TELEGRAM_BOT_TOKEN="test"', secret_envelope.env_text(values))
        for unsafe in ("", "test\nOTHER=value", "test\0value"):
            values["TELEGRAM_BOT_TOKEN"] = unsafe
            with self.assertRaises(ValueError):
                secret_envelope.env_text(values)


class ServerReceiptTests(Base):
    def test_server_persists_receipt_immediately(self):
        event = {"id": "health-test", "type": "MONITOR_HEALTH", "component": "test",
                 "detail": "offline only", "telegram_alert_status": "pending", "created_at_utc": common.utc_now()}
        payload = {"events": [event]}
        with patch.dict(os.environ, {"STOCK_DURABLE_OUTBOX": "true"}):
            self.assertTrue(notifications.deliver(payload))
        self.assertEqual(common.load_json("signal_events.json")["events"][0]["telegram_alert_status"], "sent")
        self.assertTrue(notifications.deliver(payload))
        self.assertEqual(self.post.call_count, 1)


class CutoverTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"GITHUB_RUN_ID": "777"})
        environment.start()
        self.addCleanup(environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.previous = os.getcwd()
        os.chdir(self.temporary.name)

    def tearDown(self):
        os.chdir(self.previous)
        self.temporary.cleanup()

    def test_all_legacy_workers_stopped_before_manifest(self):
        catalog = [{"id": number, "path": name} for number, name in enumerate(sorted(cutover_actions.WORKFLOWS))]
        requests = []

        def api(method, path):
            requests.append((method, path))
            if path.startswith("actions/workflows?"):
                return {"workflows": catalog}
            if path.startswith("actions/runs?"):
                return {"workflow_runs": [{"id": 888, "workflow_id": 999}]}
            if path == "branches/main":
                return {"commit": {"sha": "frozen-state"}}

        with patch.object(cutover_actions, "request", side_effect=api), patch.object(cutover_actions.time, "sleep"):
            cutover_actions.main()
        manifest = json.loads(Path("stock-cutover.json").read_text())
        self.assertEqual(manifest["source_commit"], "frozen-state")
        self.assertEqual(len([item for item in requests if item[0] == "PUT"]), 6)
        self.assertFalse(any("888/cancel" in path for method, path in requests))

    def test_missing_workflow_fails_before_disabling_anything(self):
        with patch.object(cutover_actions, "request", return_value={"workflows": []}) as api:
            with self.assertRaises(RuntimeError):
                cutover_actions.main()
        self.assertEqual(api.call_count, 1)
        self.assertFalse(Path("stock-cutover.json").exists())

    def test_moving_state_does_not_allow_takeover(self):
        catalog = [{"id": number, "path": name} for number, name in enumerate(sorted(cutover_actions.WORKFLOWS))]
        heads = iter(["first", "second"])

        def api(method, path):
            if path.startswith("actions/workflows?"):
                return {"workflows": catalog}
            if path.startswith("actions/runs?"):
                return {"workflow_runs": []}
            if path == "branches/main":
                return {"commit": {"sha": next(heads)}}

        with patch.object(cutover_actions, "request", side_effect=api), patch.object(cutover_actions.time, "sleep"):
            with self.assertRaises(RuntimeError):
                cutover_actions.main()
        self.assertFalse(Path("stock-cutover.json").exists())
