#!/bin/sh
set -eu

config_dir=${MYMPD_CONFIG_DIR:-/app/data/mympd/work/config}
state_dir=${MYMPD_STATE_DIR:-/app/data/mympd/work/state}
cache_dir=${MYMPD_CACHE_DIR:-/app/data/mympd/cache}
http_port=${MYMPD_INTERNAL_PORT:-1782}

case "$http_port" in
    *[!0-9]*|'') echo "myMPD internal port must be numeric" >&2; exit 1 ;;
esac

mkdir -p "$config_dir" "$state_dir"
write_config() {
    name=$1
    value=$2
    temp="$config_dir/.$name.$$"
    printf '%s' "$value" > "$temp"
    chmod 0600 "$temp"
    mv -f "$temp" "$config_dir/$name"
}

write_state() {
    name=$1
    value=$2
    temp="$state_dir/.$name.$$"
    printf '%s' "$value" > "$temp"
    chmod 0600 "$temp"
    mv -f "$temp" "$state_dir/$name"
}

# These settings are deliberately reconciled on every boot. myMPD persists its
# first-start values, so environment variables alone do not close an old LAN
# listener after an upgrade.
write_config http true
write_config http_host 127.0.0.1
write_config http_port "$http_port"
write_config ssl false
write_config acl +127.0.0.1
# MPD fetches native webradio playlists back from this URI. It must stay on
# loopback: the public /player/ route is intentionally protected by nginx
# session authentication and would return 401 to MPD's unauthenticated curl.
write_config mympd_uri "http://127.0.0.1:$http_port"
write_state mpd_host 127.0.0.1
write_state mpd_port 6600

style_source=/app/unified/mympd-custom.css
style_target="$config_dir/custom.css"
if [ ! -f "$style_target" ] || ! cmp -s "$style_source" "$style_target"; then
    style_temp="$config_dir/.custom.css.$$"
    cp "$style_source" "$style_temp"
    chmod 0600 "$style_temp"
    mv -f "$style_temp" "$style_target"
    # myMPD's service worker caches custom assets. Clear only its disposable
    # cache when the managed stylesheet changes so upgrades become visible.
    if [ -d "$cache_dir" ]; then
        find "$cache_dir" -mindepth 1 -maxdepth 2 -type f -delete
    fi
fi

exec /usr/bin/mympd -w /app/data/mympd/work -a /app/data/mympd/cache
