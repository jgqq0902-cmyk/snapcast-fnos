#!/bin/sh
set -eu

while ! /usr/bin/python3 -c 'import socket; s=socket.create_connection(("127.0.0.1", 6601), 1); s.close()' 2>/dev/null; do
    sleep 1
done

gateway_ip=${GATEWAY_IP:?GATEWAY_IP must be set}
case "$gateway_ip" in
    *[!0-9.]*|'') echo "Invalid GATEWAY_IP" >&2; exit 1 ;;
esac
sed "s/@GATEWAY_IP@/$gateway_ip/g" /app/unified/upmpdcli.conf > /app/data/dlna/upmpdcli.runtime.conf

exec /usr/bin/upmpdcli -c /app/data/dlna/upmpdcli.runtime.conf
