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
schema_version=${DATA_SCHEMA_VERSION:-1}
case "$schema_version" in *[!0-9]*|'') echo "DATA_SCHEMA_VERSION must be numeric" >&2; exit 1 ;; esac
schema_marker=/app/data/.snaproom-schema-version
installed_schema=0
[ ! -f "$schema_marker" ] || installed_schema=$(cat "$schema_marker")
case "$installed_schema" in *[!0-9]*|'') echo "Invalid data schema marker" >&2; exit 1 ;; esac
[ "$installed_schema" -le "$schema_version" ] || { echo "Data schema $installed_schema is newer than supported schema $schema_version" >&2; exit 1; }
printf '%s\n' "$schema_version" > "${schema_marker}.tmp"
mv "${schema_marker}.tmp" "$schema_marker"
radio_source=/app/unified/radio-stations.m3u
radio_target=/app/data/dlna/playlists/网络收音机.m3u
if [ -r "$radio_source" ] && { [ ! -f "$radio_target" ] || ! cmp -s "$radio_source" "$radio_target"; }; then
    cp "$radio_source" "${radio_target}.tmp"
    chmod 0644 "${radio_target}.tmp"
    chown snapcast:snapcast "${radio_target}.tmp"
    mv "${radio_target}.tmp" "$radio_target"
fi
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
chown snapcast:snapcast "$schema_marker"
chown -R snapcast:snapcast /app/data/nginx

web_port=${WEB_PORT:-1781}
control_port=${CONTROL_INTERNAL_PORT:-1783}
mympd_port=${MYMPD_INTERNAL_PORT:-1782}
tls_enabled=${WEB_TLS_ENABLED:-false}
case "$web_port:$control_port:$mympd_port" in
    *[!0-9:]*|:*|*:) echo "WEB_PORT, CONTROL_INTERNAL_PORT and MYMPD_INTERNAL_PORT must be numeric" >&2; exit 1 ;;
esac
tls_listen=""
tls_cert_line=""
tls_key_line=""
tls_protocols_line=""
case "$tls_enabled" in
    true|True|TRUE|1|yes|on)
        tls_cert=${TLS_CERT:-/app/certs/fullchain.pem}
        tls_key=${TLS_KEY:-/app/certs/privkey.pem}
        [ -r "$tls_cert" ] || { echo "TLS certificate is not readable: $tls_cert" >&2; exit 1; }
        [ -r "$tls_key" ] || { echo "TLS private key is not readable: $tls_key" >&2; exit 1; }
        tls_listen=" ssl"
        tls_cert_line="        ssl_certificate $tls_cert;"
        tls_key_line="        ssl_certificate_key $tls_key;"
        tls_protocols_line="        ssl_protocols TLSv1.2 TLSv1.3;"
        export CONTROL_SECURE_COOKIE=true
        ;;
    false|False|FALSE|0|no|off) export CONTROL_SECURE_COOKIE=false ;;
    *) echo "WEB_TLS_ENABLED must be true or false" >&2; exit 1 ;;
esac
sed -e "s/__WEB_PORT__/$web_port/g" \
    -e "s/__CONTROL_PORT__/$control_port/g" \
    -e "s/__MYMPD_PORT__/$mympd_port/g" \
    -e "s/__TLS_LISTEN__/$tls_listen/g" \
    -e "s#__TLS_CERT__#$tls_cert_line#g" \
    -e "s#__TLS_KEY__#$tls_key_line#g" \
    -e "s#__TLS_PROTOCOLS__#$tls_protocols_line#g" \
    /app/unified/nginx.conf > /app/data/nginx.conf
chown snapcast:snapcast /app/data/nginx.conf

exec /bin/setpriv --reuid="$puid" --regid="$pgid" --init-groups \
    /usr/bin/supervisord -c /app/unified/supervisord.conf
