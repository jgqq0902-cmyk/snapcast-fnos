#!/bin/sh
set -eu

export HOME=/data/dlna
mkdir -p /data/dlna/music /data/dlna/playlists /data/dlna/cache
touch /data/dlna/state /data/dlna/database
rm -f /data/dlna/mpd.sock

# Snapserver creates the FIFO from its pipe source.  Wait for it before MPD
# opens the FIFO so a cold start cannot turn the output into a regular file.
while [ ! -p /data/dlnafifo ]; do
    sleep 1
done

exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
