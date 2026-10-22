#!/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test -d /opt/stock-signals/deploy
id stocksignals >/dev/null 2>&1 || useradd --system --home-dir /var/lib/stock-signals --shell /usr/sbin/nologin stocksignals
install -d -m 700 -o stocksignals -g stocksignals /var/lib/stock-signals
install -d -m 700 /etc/stock-signals
python3 -m venv /opt/stock-signals/.venv
/opt/stock-signals/.venv/bin/pip install -r /opt/stock-signals/requirements.txt
chmod -R go+rX /opt/stock-signals
runuser -u stocksignals -- sh -c 'cd /opt/stock-signals && .venv/bin/python -c "import common, requests"'
install -m 644 /opt/stock-signals/deploy/stock-signals.service /etc/systemd/system/
install -m 644 /opt/stock-signals/deploy/stock-signals-watchdog.service /etc/systemd/system/
install -m 644 /opt/stock-signals/deploy/stock-signals-watchdog.timer /etc/systemd/system/
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/stock-signals.service /etc/systemd/system/stock-signals-watchdog.service
echo 'Prepared only. No stock service was started and no crypto service was changed.'
