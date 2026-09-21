#!/bin/sh
set -eu

config_dir=${MYMPD_CONFIG_DIR:-/app/data/mympd/work/config}
http_port=${MYMPD_INTERNAL_PORT:-1782}
web_port=${WEB_PORT:-1781}
gateway_ip=${GATEWAY_IP:-127.0.0.1}
scheme=http
case "${WEB_TLS_ENABLED:-false}" in true|True|TRUE|1|yes|on) scheme=https ;; esac

case "$http_port:$web_port" in
    *[!0-9:]*|:*|*:) echo "myMPD and web ports must be numeric" >&2; exit 1 ;;
esac

mkdir -p "$config_dir"
write_config() {
    name=$1
    value=$2
    temp="$config_dir/.$name.$$"
    printf '%s' "$value" > "$temp"
    chmod 0600 "$temp"
    mv -f "$temp" "$config_dir/$name"
}

# These settings are deliberately reconciled on every boot. myMPD persists its
# first-start values, so environment variables alone do not close an old LAN
# listener after an upgrade.
write_config http true
write_config http_host 127.0.0.1
write_config http_port "$http_port"
write_config ssl false
write_config acl +127.0.0.1
write_config mympd_uri "$scheme://$gateway_ip:$web_port/player/"

exec /usr/bin/mympd -w /app/data/mympd/work -a /app/data/mympd/cache
