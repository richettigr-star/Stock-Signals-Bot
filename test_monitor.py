"""Offline regression tests: no real quotes, credentials or Telegram sends."""
import contextlib
import copy
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

try:
    import requests
except ImportError:
    sys.modules["requests"] = types.SimpleNamespace(get=Mock(),post=Mock())
import common
import notifications
import scanner
import manage_state
import intraday_exit as monitor
import build_dashboard as dashboard

NOW = datetime(2026,10,15,14,20,tzinfo=timezone.utc)
class Timestamp:
    def __init__(self,value): self.value=value
    def to_pydatetime(self): return self.value
class FakeCalendar:
    def is_session(self,day):
        day=str(day)[:10]
        return datetime.fromisoformat(day).weekday()<5 and day not in {"2026-11-26","2026-12-25","2026-07-03"}
    def session_open(self,day):
        return Timestamp(datetime.fromisoformat(str(day)[:10]+"T09:30:00").replace(tzinfo=common.NY))
    def session_close(self,day):
        return Timestamp(datetime.fromisoformat(str(day)[:10]+("T13:00:00" if str(day)[:10]=="2026-11-27" else "T16:00:00")).replace(tzinfo=common.NY))
    def date_to_session(self,day,direction="next"):
        value=datetime.fromisoformat(str(day)[:10])
        while not self.is_session(value.date()):
            value+=timedelta(days=1)
        return value.date().isoformat()

def fixture_state():
    return {"positions":{"COST":{"symbol":"COST","status":"active","signal_id":"ENTRY-COST-2026-10-14",
        "signal_date":"2026-10-14","stop_usd":943.311,"initial_stop_usd":943.311,
        "last_stop_update_date":"2026-10-14"}},"closed_signals":[]}
def fixture_portfolio():
    return {"initial_capital_cad":100,"unallocated_capital_cad":66.67,"realized_pnl_cad":0,
        "holdings":{"COST":{"status":"active","entry_date":"2026-10-15",
        "entry_price_usd":985.4,"invested_cad":33.33,"strategy_stop_usd":943.311}}}
def bars(cross=False):
    start=datetime(2026,10,15,9,30)
    result=[]
    for minute in range(50):
        result.append({"datetime":(start+timedelta(minutes=minute)).isoformat(sep=" "),
            "open":980.0,"high":982.0,"low":978.0,"close":981.0})
    if cross:
        result[-1].update(low=940.0,close=950.0)
    return result
def daily_scan():
    rows=[]
    for i,symbol in enumerate(scanner.SYMBOLS):
        rows.append({"symbol":symbol,"bar_date":"2026-10-15","close_usd":1000.,
            "atr14":10.,"reference_stop_usd":975.,"eligible":i<3,"score":100-i,
            "momentum10_pct":4.,"sizing_cad":{"LIVE Small":{"risk_based_position_cad":100.}}})
    return {"latest_bar_date":"2026-10-15","all_symbols":rows,"candidates":copy.deepcopy(rows[:3]),"errors":[]}

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=os.getcwd()
        os.chdir(self.tmp.name)
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.dict(os.environ,{"TWELVE_DATA_API_KEY":"fake",
            "TELEGRAM_BOT_TOKEN":"fake","TELEGRAM_CHAT_ID":"123"}))
        self.stack.enter_context(patch.object(common,"calendar",return_value=FakeCalendar()))
        for module in (common,notifications,manage_state,monitor,dashboard):
            self.stack.enter_context(patch.object(module,"now_utc",return_value=NOW))
        self.post=self.stack.enter_context(patch.object(notifications.requests,"post",return_value=Mock(
            status_code=200,json=lambda:{"ok":True,"result":{"message_id":1}})))
        self.stack.enter_context(patch.object(notifications.time,"sleep"))
        common.save_json("signal_state.json",fixture_state())
        common.save_json("portfolio_state.json",fixture_portfolio())
        common.save_json("signal_events.json",{"events":[]})
    def tearDown(self):
        self.stack.close()
        os.chdir(self.old)
        self.tmp.cleanup()
    def run_monitor(self,data=None):
        with patch.object(monitor,"fetch_today_minute_bars",return_value=bars() if data is None else data):
            return monitor.run()

class StopTests(Base):
    def test_crossing_and_no_duplicate(self):
        self.assertEqual(self.run_monitor(bars(True)),0)
        event=common.load_json("signal_events.json")["events"][0]
        self.assertEqual(event["type"],"EXIT")
        self.assertTrue(event["holding_confirmed"])
        self.assertEqual(event["telegram_alert_status"],"sent")
        # Dashboard updates actual holding to awaiting sale; it is not sold automatically.
        dashboard.main()
        self.assertEqual(common.load_json("portfolio_state.json")["holdings"]["COST"]["status"],
                         "exit_alert_awaiting_manual_sale")
        self.run_monitor()
        exits=[e for e in common.load_json("signal_events.json")["events"] if e["type"]=="EXIT"]
        self.assertEqual(len(exits),1)
    def test_no_cross_keeps_holding(self):
        self.assertEqual(self.run_monitor(),0)
        self.assertIn("COST",common.load_json("signal_state.json")["positions"])
    def test_old_bars_do_not_use_future_stop(self):
        p=fixture_state()["positions"]["COST"]
        p["stop_usd"]=990
        p["stop_history"]=[{"stop_usd":990,"effective_from_utc":"2026-10-16T13:30:00+00:00"}]
        self.assertEqual(monitor.applicable_stop(p,NOW),943.311)
    def test_pre_entry_bar_ignored(self):
        state=fixture_state()
        state["positions"]["COST"]["actual_fill"]={"execution_time":"2026-10-15T14:19:30+00:00"}
        common.save_json("signal_state.json",state)
        self.assertEqual(self.run_monitor(bars(True)),0)
        self.assertIn("COST",common.load_json("signal_state.json")["positions"])
    def test_unbought_signal_does_not_instruct_sell(self):
        p=fixture_portfolio()
        p["holdings"]={}
        common.save_json("portfolio_state.json",p)
        self.run_monitor(bars(True))
        text=self.post.call_args.kwargs["data"]["text"]
        self.assertIn("sinal teórico",text)
        self.assertNotIn("execute a saída",text)
    def test_stale_data_is_failure(self):
        self.assertEqual(self.run_monitor(bars()[:1]),1)
        self.assertEqual(common.load_json("monitor_health.json")["status"],"degraded")
    def test_missing_history_is_visible(self):
        self.assertEqual(self.run_monitor(bars()[20:]),1)
        self.assertTrue(common.load_json("monitor_health.json")["symbols"]["COST"]["recovery_gap_detected"])
    def test_future_bar_does_not_trigger_exit(self):
        data=bars()
        data.append({"datetime":"2026-10-15 12:00:00","open":950,"high":960,"low":930,"close":950})
        self.assertEqual(self.run_monitor(data),0)
        self.assertIn("COST",common.load_json("signal_state.json")["positions"])
    def test_data_error_preserves_state_and_alerts(self):
        with patch.object(monitor,"fetch_today_minute_bars",side_effect=RuntimeError("secret-url")):
            self.assertEqual(monitor.run(),1)
        self.assertIn("COST",common.load_json("signal_state.json")["positions"])
        self.assertNotIn("secret-url",Path("monitor_health.json").read_text())
    def test_corrupt_state_fails_closed(self):
        Path("signal_state.json").write_text("{broken")
        self.assertEqual(self.run_monitor(),1)
        self.assertEqual(Path("signal_state.json").read_text(),"{broken")
    def test_missing_holding_monitor_is_failure(self):
        common.save_json("signal_state.json",{"positions":{}})
        self.assertEqual(self.run_monitor(),1)

class NotificationTests(Base):
    def event(self,kind="ENTRY"):
        value={"id":"test","type":kind,"symbol":"COST","signal_date":"2026-10-15",
           "created_at_utc":NOW.isoformat(),"recommended_position_cad":10.,"stop_usd":900.}
        if kind=="EXIT":
            value.update(trigger_bar_datetime_ny="2026-10-15 09:31:00",trigger_bar_low_usd=890.)
        return value
    def test_next_open_entry_not_expired_after_two_hours(self):
        e=self.event()
        e["created_at_utc"]="2026-10-14T20:20:00+00:00"
        self.assertTrue(notifications.deliver({"events":[e]}))
        self.assertEqual(e["telegram_alert_status"],"sent")
    def test_entry_expired_after_intended_open(self):
        e=self.event()
        e["signal_date"]="2026-10-14"
        notifications.deliver({"events":[e]})
        self.assertEqual(e["telegram_alert_status"],"skipped_stale")
        self.post.assert_not_called()
    def test_telegram_ok_false_is_failure(self):
        self.post.return_value=Mock(status_code=200,json=lambda:{"ok":False})
        e=self.event("EXIT")
        self.assertFalse(notifications.deliver({"events":[e]}))
        self.assertEqual(e["telegram_alert_status"],"failed")
    def test_already_sent_not_replayed(self):
        e=self.event()
        e["telegram_alert_status"]="sent"
        notifications.deliver({"events":[e]})
        self.post.assert_not_called()
    def test_unsent_entry_retried_by_intraday_monitor(self):
        e=self.event()
        common.save_json("signal_events.json",{"events":[e]})
        self.run_monitor()
        saved=common.load_json("signal_events.json")["events"][0]
        self.assertEqual(saved["telegram_alert_status"],"sent")
    def test_late_exit_is_labeled(self):
        e=self.event("EXIT")
        e["created_at_utc"]="2026-10-15T12:00:00+00:00"
        notifications.deliver({"events":[e]})
        self.assertIn("atrasada",self.post.call_args.kwargs["data"]["text"])
    def test_unsent_events_not_trimmed(self):
        p={"events":[dict(self.event(),id=str(i)) for i in range(510)]}
        common.append_event(p,dict(self.event(),id="new"))
        self.assertEqual(len(p["events"]),511)

class DailyTests(Base):
    def after_close(self):
        value=datetime(2026,10,15,20,20,tzinfo=timezone.utc)
        for module in (common,notifications,manage_state,monitor,dashboard):
            self.stack.enter_context(patch.object(module,"now_utc",return_value=value))
    def test_incomplete_daily_candle_rejected(self):
        self.assertFalse(manage_state.scan_is_complete_and_fresh(daily_scan())[0])
    def test_complete_scan_accepted_after_close(self):
        self.after_close()
        self.assertTrue(manage_state.scan_is_complete_and_fresh(daily_scan())[0])
    def test_missing_symbol_rejected(self):
        self.after_close()
        data=daily_scan()
        data["all_symbols"].pop()
        self.assertFalse(manage_state.scan_is_complete_and_fresh(data)[0])
    def test_mixed_date_rejected(self):
        self.after_close()
        data=daily_scan()
        data["all_symbols"][0]["bar_date"]="2026-10-14"
        self.assertFalse(manage_state.scan_is_complete_and_fresh(data)[0])
    def test_wrong_rank_rejected(self):
        self.after_close()
        data=daily_scan()
        data["candidates"].reverse()
        self.assertFalse(manage_state.scan_is_complete_and_fresh(data)[0])
    def test_trailing_never_falls_and_is_idempotent(self):
        self.after_close()
        data=daily_scan()
        cost=next(r for r in data["all_symbols"] if r["symbol"]=="COST")
        cost.update(close_usd=900.,atr14=10.,reference_stop_usd=875.)
        common.save_json("signals.json",data)
        self.assertEqual(manage_state.main(),0)
        state=common.load_json("signal_state.json")
        self.assertEqual(state["positions"]["COST"]["stop_usd"],943.311)
        count=len(common.load_json("signal_events.json")["events"])
        manage_state.main()
        self.assertEqual(len(common.load_json("signal_events.json")["events"]),count)
    def test_trailing_rise_only_effective_next_session(self):
        self.after_close()
        common.save_json("signals.json",daily_scan())
        manage_state.main()
        p=common.load_json("signal_state.json")["positions"]["COST"]
        self.assertEqual(p["stop_usd"],975.)
        self.assertEqual(monitor.applicable_stop(p,NOW),943.311)
        self.assertEqual(monitor.applicable_stop(p,datetime(2026,10,16,14,tzinfo=timezone.utc)),975.)
    def test_recommendations_respect_remaining_cash(self):
        self.after_close()
        common.save_json("signals.json",daily_scan())
        manage_state.main()
        entries=[e for e in common.load_json("signal_events.json")["events"] if e["type"]=="ENTRY"]
        self.assertLessEqual(sum(e["recommended_position_cad"] for e in entries),66.67)
    def test_dashboard_totals_not_hardcoded(self):
        p=fixture_portfolio()
        p["initial_capital_cad"]=200
        common.save_json("portfolio_state.json",p)
        dashboard.main()
        self.assertIn("C$ 200.00",Path("dashboard.md").read_text())
        self.assertEqual(common.load_json("portfolio_state.json")["unallocated_capital_cad"],166.67)
    def test_bad_ohlc_rejected(self):
        with self.assertRaises(ValueError):
            common.validate_ohlc({"open":10,"high":9,"low":8,"close":10})
    def test_nan_price_rejected(self):
        with self.assertRaises(ValueError):
            common.validate_ohlc({"open":10,"high":float("nan"),"low":8,"close":10})

class ExtraRegressionTests(Base):
    def test_wilder_atr_reference_vector(self):
        self.assertEqual(scanner.wilder_atr([12,13,15,14],[10,11,11,10],[11,12,14,11],3),
                         [None,None,8/3,(8/3*2+4)/3])
    def test_ema_reference_vector(self):
        self.assertEqual(scanner.ema([10,12,14],3),[10,11,12.5])
    def test_failed_exit_stays_in_outbox(self):
        self.post.side_effect=RuntimeError("secret-token-url")
        self.assertEqual(self.run_monitor(bars(True)),1)
        events=common.load_json("signal_events.json")["events"]
        self.assertEqual(events[0]["telegram_alert_status"],"failed")
        self.assertNotIn("secret-token-url",Path("signal_events.json").read_text())
    def test_http_errors_do_not_expose_market_key(self):
        response=Mock(status_code=401)
        with patch.object(monitor.requests,"get",return_value=response):
            with self.assertRaises(RuntimeError) as captured:
                monitor.fetch_today_minute_bars("COST","private-key")
        self.assertNotIn("private-key",str(captured.exception))
    def test_duplicate_minutes_rejected(self):
        value={"datetime":"2026-10-15 10:19:00","open":"980","high":"982","low":"978","close":"981"}
        response=Mock(status_code=200,json=lambda:{"meta":{"symbol":"COST"},"values":[value,value]})
        with patch.object(monitor.requests,"get",return_value=response):
            with self.assertRaises(RuntimeError):
                monitor.fetch_today_minute_bars("COST","private-key")
    def test_historical_exit_recovery_is_labeled_delayed(self):
        later=NOW+timedelta(hours=3)
        with patch.object(monitor,"now_utc",return_value=later),patch.object(notifications,"now_utc",return_value=later):
            self.run_monitor(bars(True))
        event=next(e for e in common.load_json("signal_events.json")["events"] if e["type"]=="EXIT")
        self.assertTrue(event["delivery_delayed"])
    def test_daily_runner_does_not_scan_intraday(self):
        import daily_runner
        with patch.object(daily_runner,"now_utc",return_value=NOW),patch.object(daily_runner.rate_limited_scanner.scanner,"main") as scan:
            self.assertEqual(daily_runner.main(),0)
            scan.assert_not_called()
    def test_after_close_recovery_checks_stop_before_raising(self):
        later=datetime(2026,10,15,23,tzinfo=timezone.utc)
        data=bars(True)
        with patch.object(monitor,"now_utc",return_value=later),patch.object(monitor,"fetch_today_minute_bars",return_value=data):
            monitor.run(catch_up=True)
        self.assertNotIn("COST",common.load_json("signal_state.json")["positions"])

@unittest.skipUnless(importlib.util.find_spec("exchange_calendars"),"calendar package runs in GitHub CI")
class RealCalendarTests(unittest.TestCase):
    def test_thanksgiving_closed(self):
        self.assertIsNone(common.session_bounds("2026-11-26"))
    def test_black_friday_early_close(self):
        self.assertEqual(common.session_bounds("2026-11-27")[1].astimezone(common.NY).hour,13)
    def test_dst_open_utc_changes(self):
        self.assertEqual(common.session_bounds("2026-10-15")[0].hour,13)
        self.assertEqual(common.session_bounds("2026-11-05")[0].hour,14)
    def test_christmas_next_open_skips_weekend(self):
        self.assertEqual(common.next_open("2026-12-24").astimezone(common.NY).date().isoformat(),"2026-12-28")
if __name__=="__main__":
    unittest.main()
