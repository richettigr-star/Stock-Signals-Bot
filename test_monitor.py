import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime as RealDatetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.modules.setdefault("requests", types.ModuleType("requests"))
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

monitor = module("intraday_exit")
dashboard = module("build_dashboard")
class Clock(RealDatetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 15, 14, 20, tzinfo=monitor.timezone.utc).astimezone(tz)

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)
        monitor.HEALTH.clear()
        self.env = patch.dict(os.environ, {"TWELVE_DATA_API_KEY":"test", "TELEGRAM_BOT_TOKEN":"", "TELEGRAM_CHAT_ID":""})
        self.env.start()
        Path("signal_state.json").write_text(json.dumps({"positions":{"COST":{"symbol":"COST","status":"active","signal_date":"2026-10-14","stop_usd":943.311}},"closed_signals":[]}))
        Path("portfolio_state.json").write_text(json.dumps({"holdings":{"COST":{"status":"active","entry_date":"2026-10-15","entry_price_usd":985.4,"strategy_stop_usd":943.311}}}))
    def tearDown(self):
        self.env.stop()
        os.chdir(self.old)
        self.tmp.cleanup()
    def bar(self, low=940, at="2026-10-15 10:19:00"):
        return [{"datetime":at,"open":980,"high":981,"low":low,"close":950}]
    def run_monitor(self, bars):
        with patch.object(monitor, "datetime", Clock), patch.object(monitor, "fetch_today_minute_bars", return_value=bars):
            return monitor.main()
    def test_stop_crossing_no_duplicate_or_assumed_sale(self):
        self.assertEqual(self.run_monitor(self.bar()), 0)
        self.assertNotIn("COST", json.loads(Path("signal_state.json").read_text())["positions"])
        events = json.loads(Path("signal_events.json").read_text())["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["telegram_alert_status"], "not_configured")
        self.run_monitor(self.bar())
        self.assertEqual(len(json.loads(Path("signal_events.json").read_text())["events"]), 1)
        monitor.HEALTH["completed_at_utc"] = Clock.now(monitor.timezone.utc).isoformat()
        Path("monitor_health.json").write_text(json.dumps(monitor.HEALTH))
        dashboard.main()
        holding = json.loads(Path("portfolio_state.json").read_text())["holdings"]["COST"]
        self.assertEqual(holding["status"], "exit_alert_awaiting_manual_sale")
        self.assertIn("not_configured", Path("dashboard.md").read_text())
    def test_stale_data_degrades_monitor(self):
        self.assertEqual(self.run_monitor(self.bar(low=950, at="2026-10-15 09:35:00")), 1)
        self.assertEqual(monitor.HEALTH["status"], "degraded")
        self.assertEqual(monitor.HEALTH["symbols"]["COST"]["status"], "stale")
    def test_api_failure_is_visible_and_keeps_holding(self):
        with patch.object(monitor, "datetime", Clock), patch.object(monitor, "fetch_today_minute_bars", side_effect=RuntimeError("private-url")):
            self.assertEqual(monitor.main(), 1)
        self.assertEqual(monitor.HEALTH["symbols"]["COST"]["status"], "error")
        self.assertIn("COST", json.loads(Path("signal_state.json").read_text())["positions"])
    def test_dashboard_reads_new_trailing_stop(self):
        data=json.loads(Path("signal_state.json").read_text())
        data["positions"]["COST"]["stop_usd"]=955.0
        Path("signal_state.json").write_text(json.dumps(data))
        dashboard.main()
        self.assertEqual(json.loads(Path("portfolio_state.json").read_text())["holdings"]["COST"]["strategy_stop_usd"],955)
        self.assertIn("955.0000",Path("dashboard.md").read_text())

if __name__ == "__main__":
    unittest.main()
