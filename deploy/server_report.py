"""Read-only operational snapshot of the local stock service."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import load_json, now_utc, utc_now
from verify_cadence import assess


def report():
    state = load_json("signal_state.json", required=True)
    portfolio = load_json("portfolio_state.json", required=True)
    cadence = load_json("monitor_cadence.json", {"samples": []})
    samples = [item for item in cadence["samples"] if str(item.get("run_id", "")).startswith("server-")]
    pending = [item["id"] for item in load_json("signal_events.json", {"events": []})["events"]
               if item.get("telegram_alert_status") in {"pending", "failed", "not_configured"}]
    return {"observed_at_utc": utc_now(), "source": load_json("migration_source.json", {}),
            "monitor": load_json("monitor_health.json", {}),
            "supervisor": load_json("supervisor_health.json", {}),
            "watchdog": load_json("watchdog_health.json", {}),
            "daily": load_json("daily_health.json", {}),
            "server_cadence": assess({"samples": samples}, now_utc()),
            "latest_server_samples": samples[-4:], "undelivered_event_ids": pending,
            "confirmed_holdings": {symbol: {"status": item.get("status"),
                                            "strategy_stop_usd": item.get("strategy_stop_usd")}
                                   for symbol, item in portfolio["holdings"].items() if item.get("status") != "closed"},
            "positions": {symbol: {"status": item["status"], "stop_usd": item["stop_usd"]}
                          for symbol, item in state["positions"].items()},
            "backup_count": len(list(Path("backups").glob("*.tar.gz")))}


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
