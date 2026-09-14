#!/bin/sh
set -eu

pgrep -x snapserver >/dev/null
pgrep -x avahi-daemon >/dev/null
pgrep -x shairport-sync >/dev/null
pgrep -x mpd >/dev/null
pgrep -x upmpdcli >/dev/null
pgrep -f '/app/control/app.py' >/dev/null
test -p /app/data/airplayfifo
test -p /app/data/dlnafifo

exec /usr/bin/python3 -c 'import json, urllib.request; state=json.load(urllib.request.urlopen("http://127.0.0.1:1781/api/health", timeout=2)); assert state["ok"], state'
