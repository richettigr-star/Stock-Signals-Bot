"""Import the frozen GitHub stock snapshot once, without changing its contents."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys

FILES = ("signal_state.json", "portfolio_state.json", "signal_events.json", "signals.json",
         "monitor_health.json", "monitor_cadence.json", "watchdog_health.json",
         "supervisor_health.json", "daily_health.json")


def validate(payloads):
    state = json.loads(payloads["signal_state.json"])
    portfolio = json.loads(payloads["portfolio_state.json"])
    holdings = {symbol: item for symbol, item in portfolio["holdings"].items() if item.get("status") != "closed"}
    if set(holdings) != {"COST"}:
        raise ValueError("Confirmed holdings changed; reconcile before migration")
    position = state["positions"].get("COST", {})
    if position.get("status") != "active" or float(position.get("stop_usd", 0)) < 959.1617:
        raise ValueError("Current COST stop/position not preserved")
    for symbol, item in state["positions"].items():
        if symbol != "COST" and item.get("status") != "pending_entry":
            raise ValueError("Unconfirmed signal unexpectedly active")
    for content in payloads.values():
        if not isinstance(json.loads(content), dict):
            raise ValueError("Invalid state object")
    return position["stop_usd"]


def main(sha, destination):
    if not re.fullmatch("[a-f0-9]{40}", sha):
        raise ValueError("Expected immutable source commit")
    target = Path(destination)
    if any((target / name).exists() for name in FILES):
        raise RuntimeError("Refusing to replace existing live state")
    payloads = {name: subprocess.check_output(["git", "show", sha + ":" + name]) for name in FILES}
    stop = validate(payloads)
    account = pwd.getpwnam("stocksignals")
    os.umask(0o077)
    target.mkdir(mode=0o700, exist_ok=True)
    for name, content in payloads.items():
        with (target / name).open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(target / name, account.pw_uid, account.pw_gid)
    manifest = {"source_commit": sha, "cost_stop_usd": stop,
                "sha256": {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()}}
    (target / "migration_source.json").write_text(json.dumps(manifest, indent=2))
    os.chown(target / "migration_source.json", account.pw_uid, account.pw_gid)
    print("Imported exact frozen state. Confirmed: COST only. Stop USD:", stop)


if __name__ == "__main__":
    main(*sys.argv[1:])
