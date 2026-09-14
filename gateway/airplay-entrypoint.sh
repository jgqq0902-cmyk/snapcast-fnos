#!/bin/sh
set -eu

dbus-uuidgen --ensure 2>/dev/null || true

# Snapserver creates the FIFO from its pipe source.  Wait for it before
# starting Shairport Sync so a cold start cannot open a regular file instead.
while [ ! -p /app/data/airplayfifo ]; do
    sleep 1
done

exec /usr/bin/supervisord -c /app/gateway/supervisord.conf
