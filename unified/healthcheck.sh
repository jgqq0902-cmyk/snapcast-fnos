#!/bin/sh
set -eu

pgrep -x snapserver >/dev/null
pgrep -x avahi-daemon >/dev/null
pgrep -x shairport-sync >/dev/null
pgrep -x mpd >/dev/null
pgrep -x mympd >/dev/null
pgrep -x upmpdcli >/dev/null
pgrep -x nginx >/dev/null
pgrep -f '/app/control/app.py' >/dev/null
test -p /app/data/airplayfifo
test -p /app/data/dlnafifo
internal_mympd_port=${MYMPD_INTERNAL_PORT:-1782}
web_port=${WEB_PORT:-1781}
wget -qO- "http://127.0.0.1:$internal_mympd_port/" >/dev/null

exec /usr/bin/python3 -c "import json, urllib.request; state=json.load(urllib.request.urlopen('http://127.0.0.1:$web_port/api/health', timeout=2)); assert state['ok'], state"
