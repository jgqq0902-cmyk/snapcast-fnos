#!/bin/sh
set -eu

project_dir=/vol1/1000/tools/snapcast
backup_dir="$project_dir/backups/20260913-euphonica-predeploy"
backup_image=snapcast-all-in-one:backup-20260913-euphonica

cd "$project_dir"
mkdir -p "$backup_dir"
cp docker-compose.yml "$backup_dir/docker-compose.yml"
cp unified/Dockerfile "$backup_dir/Dockerfile"
docker cp snapcast:/app/control "$backup_dir/control-running"

old_image=$(docker inspect --format '{{.Image}}' snapcast)
docker image tag "$old_image" "$backup_image"

docker compose config -q
docker compose build

if docker compose up -d --remove-orphans --wait --wait-timeout 180; then
    docker exec snapcast wget -qO- http://127.0.0.1:1781/api/health
    echo
    echo "Snap/Room 3 deployment is healthy."
    exit 0
fi

echo "Deployment failed; restoring previous image." >&2
docker image tag "$backup_image" snapcast-all-in-one:local
docker compose up -d --remove-orphans --wait --wait-timeout 180
exit 1
