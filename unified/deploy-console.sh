#!/bin/sh
set -eu

project_dir=${PROJECT_DIR:-/vol1/1000/tools/snapcast}
timestamp=$(date +%Y%m%d-%H%M%S)
backup_dir="$project_dir/backups/$timestamp-audit-remediation"
backup_image="snapcast-all-in-one:backup-$timestamp"

cd "$project_dir"
[ -f .env ] || { echo "Missing .env; copy .env.example and configure it first." >&2; exit 1; }
password=$(sed -n 's/^CONTROL_PASSWORD=//p' .env | tail -n 1)
auth_enabled=$(sed -n 's/^CONTROL_AUTH_ENABLED=//p' .env | tail -n 1)
case "$auth_enabled" in
    false|False|FALSE|0|no|off) ;;
    *)
        [ -n "$password" ] || { echo "CONTROL_PASSWORD must not be empty when authentication is enabled." >&2; exit 1; }
        [ "$password" != "replace-with-a-long-random-password" ] || { echo "Replace the example CONTROL_PASSWORD before deployment." >&2; exit 1; }
        ;;
esac

mkdir -p "$backup_dir"
cp docker-compose.yml snapserver.conf "$backup_dir/"
[ ! -f config/snapserver.conf ] || cp config/snapserver.conf "$backup_dir/snapserver.runtime.conf"
docker cp snapcast:/app/control "$backup_dir/control-running" 2>/dev/null || true

old_image=$(docker inspect --format '{{.Image}}' snapcast)
docker image tag "$old_image" "$backup_image"

docker compose config -q
docker compose build
mkdir -p config
cp snapserver.conf config/snapserver.conf

if docker compose up -d --remove-orphans --wait --wait-timeout 180 \
    && docker exec snapcast /app/unified/smoke-test.sh; then
    echo "Deployment is healthy. Backup: $backup_dir; image: $backup_image"
    exit 0
fi

echo "Deployment failed; restoring the previous runtime config and image." >&2
if [ -f "$backup_dir/snapserver.runtime.conf" ]; then
    cp "$backup_dir/snapserver.runtime.conf" config/snapserver.conf
fi
docker image tag "$backup_image" snapcast-all-in-one:local
docker compose up -d --remove-orphans --wait --wait-timeout 180
exit 1
