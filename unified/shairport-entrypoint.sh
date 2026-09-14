#!/bin/sh
set -eu

while ! avahi-daemon --check >/dev/null 2>&1 || [ ! -S /run/avahi-daemon/socket ]; do
    sleep 1
done

while [ ! -p /app/data/airplayfifo ]; do
    sleep 1
done

exec /usr/local/bin/shairport-sync \
    --service-type=classic \
    --mdns=avahi \
    --name=Snapcast-AirPlay \
    --output=stdout \
    --port=5000 \
    --verbose \
    >/app/data/airplayfifo
