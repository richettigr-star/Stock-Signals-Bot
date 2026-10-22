"""Approved one-time freeze of GitHub stock writers before local state takeover."""
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

WORKFLOWS = {"daily-signals.yml", "intraday-exits.yml", "monitor-watchdog.yml",
             "session-supervisor.yml", "telegram-trade-status.yml", "test-emergency-telegram.yml"}


def request(method, path):
    url = "https://api.github.com/repos/richettigr-star/Stock-Signals-Bot/" + path
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
        return json.loads(data) if data else None


def main():
    catalog = request("GET", "actions/workflows?per_page=100")["workflows"]
    selected = [item for item in catalog if item["path"].split("/")[-1] in WORKFLOWS]
    if {item["path"].split("/")[-1] for item in selected} != WORKFLOWS:
        raise RuntimeError("Cannot identify all legacy stock workflows")
    ids = {item["id"] for item in selected}
    for item in selected:
        request("PUT", f"actions/workflows/{item['id']}/disable")
    deadline = time.monotonic() + 240
    cancelled = set()
    while True:
        active = []
        for status in ("in_progress", "queued", "pending", "waiting", "requested"):
            for page in range(1, 21):
                batch = request("GET", f"actions/runs?status={status}&per_page=100&page={page}")["workflow_runs"]
                active.extend(item for item in batch if item["workflow_id"] in ids
                              and str(item["id"]) != os.environ["GITHUB_RUN_ID"])
                if len(batch) < 100:
                    break
            else:
                raise RuntimeError("Too many pending runs; manual audit required")
        if not active:
            break
        for item in active:
            try:
                suffix = "force-cancel" if item["id"] in cancelled else "cancel"
                request("POST", f"actions/runs/{item['id']}/{suffix}")
                cancelled.add(item["id"])
            except urllib.error.HTTPError as error:
                if error.code != 409:
                    raise
        if time.monotonic() > deadline:
            raise RuntimeError("Stock workers did not stop; do not start server")
        time.sleep(10)
    sha = request("GET", "branches/main")["commit"]["sha"]
    time.sleep(10)
    if request("GET", "branches/main")["commit"]["sha"] != sha:
        raise RuntimeError("Repository still changing; do not import state")
    Path("stock-cutover.json").write_text(json.dumps({"source_commit": sha,
        "disabled_workflows": sorted(WORKFLOWS), "cancelled_runs": sorted(cancelled),
        "current_run": os.environ["GITHUB_RUN_ID"], "status": "legacy_writers_stopped"}, indent=2))
    print("All legacy stock workflows disabled and stopped; state commit=" + sha)


if __name__ == "__main__":
    main()
