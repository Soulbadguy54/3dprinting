#!/usr/bin/env bash
# Invoked via the root-owned, main-branch staging dispatcher.
# The compose definition is read from reviewed main, never from develop.
set -euo pipefail
umask 077
sha="${1:?stage SHA required}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
cd /srv/rateapp/source
test -f /srv/rateapp/stage-initialized
test -r /srv/rateapp/secrets/stage_postgres_password
export RATEAPP_STAGE_RELEASE="$sha"
export DOCKER_CONFIG
DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
IFS= read -r registry_token
test -n "$registry_token" || { echo 'Missing registry token' >&2; exit 2; }
printf '%s\n' "$registry_token" | docker login ghcr.io -u Soulbadguy54 --password-stdin >/dev/null
unset registry_token

compose=(docker compose -f deploy/compose.stage.yaml)
"${compose[@]}" pull api web
# Back up only staging prior to applying its own migrations.
install -d -m 0700 /srv/rateapp/backups/staging-predeploy
archive="/srv/rateapp/backups/staging-predeploy/$sha-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec rateapp-postgres pg_dump -U rateapp -d rateapp_stage -Fc > "$archive"
test -s "$archive"
docker exec -i rateapp-postgres pg_restore --list < "$archive" >/dev/null
"${compose[@]}" run --rm api python -m alembic upgrade head

previous=""
test ! -f /srv/rateapp/stage-current-release || previous="$(cat /srv/rateapp/stage-current-release)"
"${compose[@]}" up -d api web
for attempt in $(seq 1 24); do
  if curl -fsS --max-time 6 http://127.0.0.1:18081/api/health |
    python3 -c 'import json,sys;assert json.load(sys.stdin)["database"]["reachable"] is True' >/dev/null 2>&1; then
    printf '%s\n' "$sha" > /srv/rateapp/stage-current-release
    echo "Staging healthy at $sha"
    exit 0
  fi
  sleep 5
done
echo "Staging API unhealthy" >&2
if [[ "$previous" =~ ^[0-9a-f]{40}$ ]]; then
  export RATEAPP_STAGE_RELEASE="$previous"
  "${compose[@]}" up -d api web || true
fi
# Database schemas must never be automatically downgraded.
exit 1
