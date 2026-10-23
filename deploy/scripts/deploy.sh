#!/usr/bin/env bash
# Called by GitHub Actions through SSH; never log secrets or the registry token.
set -euo pipefail
umask 077
sha="${1:?release SHA required}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release SHA' >&2; exit 2; }
cd /srv/rateapp/source
test -f /srv/rateapp/secrets/app.env
test -f /srv/rateapp/secrets/postgres_password
test -f deploy/compose.yaml
export RATEAPP_RELEASE="$sha"
# Authenticate to private GHCR packages using the short-lived GitHub Actions token via stdin.
# DOCKER_CONFIG is isolated to this invocation and removed on exit.
export DOCKER_CONFIG
DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
IFS= read -r registry_token
test -n "$registry_token" || { echo 'Missing registry token' >&2; exit 2; }
printf '%s\n' "$registry_token" | docker login ghcr.io -u Soulbadguy54 --password-stdin >/dev/null
unset registry_token
compose=(docker compose -f deploy/compose.yaml)
"${compose[@]}" pull api web
"${compose[@]}" up -d db
# A local pre-migration safety copy; off-site scheduled backups are configured separately.
backup_dir=/srv/rateapp/backups/predeploy
install -d -m 0700 "$backup_dir"
archive="$backup_dir/$sha-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec rateapp-postgres pg_dump -U rateapp -d rateapp -Fc > "$archive"
test -s "$archive"
docker exec -i rateapp-postgres pg_restore --list < "$archive" >/dev/null
"${compose[@]}" run --rm api python -m alembic upgrade head
previous=""
test ! -f /srv/rateapp/current-release || previous="$(cat /srv/rateapp/current-release)"
"${compose[@]}" up -d --no-deps api web
healthy=0
for attempt in $(seq 1 24); do
  if curl -fsS --max-time 8 http://127.0.0.1:18080/api/health | python3 -c 'import json,sys; x=json.load(sys.stdin); assert x["database"]["reachable"] is True' >/dev/null 2>&1; then
    healthy=1; break
  fi
  sleep 5
done
if [[ "$healthy" != 1 ]]; then
  echo "Health check failed after deployment" >&2
  if [[ "$previous" =~ ^[0-9a-f]{40}$ ]]; then
    echo 'Reverting application images (database migrations are NOT rolled back)' >&2
    export RATEAPP_RELEASE="$previous"
    "${compose[@]}" up -d --no-deps api web || true
  fi
  exit 1
fi
printf '%s\n' "$sha" > /srv/rateapp/current-release
# Install the independently constrained staging dispatcher only from reviewed main.
install -o root -g root -m 0755 deploy/scripts/ssh-deploy-dispatch.sh /usr/local/sbin/rateapp-deploy-dispatch
install -o root -g root -m 0755 deploy/scripts/ssh-stage-deploy-root.sh /usr/local/sbin/rateapp-stage-deploy-root
printf '%s\n' 'rateapp-deploy ALL=(root) NOPASSWD: /usr/local/sbin/rateapp-stage-deploy-root *' > /etc/sudoers.d/rateapp-stage-deploy
chmod 0440 /etc/sudoers.d/rateapp-stage-deploy
visudo -cf /etc/sudoers.d/rateapp-stage-deploy >/dev/null
echo "Rate APP healthy at $sha"
