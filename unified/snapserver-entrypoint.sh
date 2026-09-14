#!/bin/sh
set -eu

while ! avahi-daemon --check >/dev/null 2>&1; do
    sleep 1
done

exec /usr/bin/snapserver -c /app/config/snapserver.conf --server.datadir=/app/data
