#!/bin/sh
set -eu

umask 0002

puid=${PUID:-1000}
pgid=${PGID:-1000}
case "$puid:$pgid" in
    *[!0-9:]*|:*|*:) echo "PUID and PGID must be numeric" >&2; exit 1 ;;
esac
sed -i -E "s#^(snapcast:x:)[0-9]+:[0-9]+:#\\1${puid}:${pgid}:#" /etc/passwd
sed -i -E "s#^(snapcast:x:)[0-9]+:#\\1${pgid}:#" /etc/group

dbus-uuidgen --ensure 2>/dev/null || true
mkdir -p /app/data/dlna/music /app/data/dlna/playlists /app/data/dlna/cache \
         /app/data/mympd/work /app/data/mympd/cache \
         /app/data/nginx/client_body /app/data/nginx/proxy /app/data/nginx/fastcgi \
         /app/data/nginx/uwsgi /app/data/nginx/scgi /app/data/nginx/logs
if [ ! -e /app/data/dlna/library ] && [ ! -L /app/data/dlna/library ]; then
    ln -s /media/music /app/data/dlna/library
fi
rm -f /app/data/dlna/mpd.sock \
      /app/data/dlna/mpd.pid \
      /app/data/dlna/upmpdcli.pid \
      /app/data/unified-supervisord.pid \
      /app/data/nginx.pid

ownership_marker="/app/data/.owner-${puid}-${pgid}"
if [ ! -f "$ownership_marker" ]; then
    chown -R snapcast:snapcast /app/data
    find /app/data -maxdepth 1 -type f -name '.owner-*' -delete
    : > "$ownership_marker"
    chown snapcast:snapcast "$ownership_marker"
fi
chown -R snapcast:snapcast /app/data/nginx

web_port=${WEB_PORT:-1781}
control_port=${CONTROL_INTERNAL_PORT:-1783}
mympd_port=${MYMPD_INTERNAL_PORT:-1782}
case "$web_port:$control_port:$mympd_port" in
    *[!0-9:]*|:*|*:) echo "WEB_PORT, CONTROL_INTERNAL_PORT and MYMPD_INTERNAL_PORT must be numeric" >&2; exit 1 ;;
esac
sed -e "s/__WEB_PORT__/$web_port/g" \
    -e "s/__CONTROL_PORT__/$control_port/g" \
    -e "s/__MYMPD_PORT__/$mympd_port/g" \
    /app/unified/nginx.conf > /app/data/nginx.conf
chown snapcast:snapcast /app/data/nginx.conf

exec /usr/bin/supervisord -c /app/unified/supervisord.conf
