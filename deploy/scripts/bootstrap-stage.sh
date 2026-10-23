#!/usr/bin/env bash
# Bootstrap staging only; requires an approved main revision and isolated database role.
set -euo pipefail
umask 077
sha="${1:?main release SHA required}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
cd /srv/rateapp/source
test "$(cat /srv/rateapp/current-release)" = "$sha"
test ! -e /srv/rateapp/stage-initialized || { echo "Staging already initialized"; exit 0; }

install -d -m 0700 /srv/rateapp/backups/staging-bootstrap
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
source_archive="/srv/rateapp/backups/staging-bootstrap/production-$stamp.dump"
docker exec rateapp-postgres pg_dump -U rateapp -d rateapp -Fc > "$source_archive"
docker exec -i rateapp-postgres pg_restore --list < "$source_archive" >/dev/null

# Safeguard any existing staging test data before replacing the initial snapshot.
docker exec rateapp-postgres pg_dump -U rateapp -d rateapp_stage -Fc > "/srv/rateapp/backups/staging-bootstrap/previous-stage-$stamp.dump"
stage_password_file=/srv/rateapp/secrets/stage_postgres_password
if [[ ! -e "$stage_password_file" ]]; then
  openssl rand -hex 32 > "$stage_password_file"
  chmod 0600 "$stage_password_file"
fi
stage_password="$(cat "$stage_password_file")"
docker exec -i rateapp-postgres psql -U rateapp -d postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
DO \$\$ BEGIN
IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rateapp_stage') THEN
  CREATE ROLE rateapp_stage LOGIN;
END IF;
END \$\$;
ALTER ROLE rateapp_stage WITH PASSWORD '$stage_password';
SQL
unset stage_password

# Replacement is confined to rateapp_stage, never the production database.
docker exec rateapp-postgres dropdb -U rateapp --force rateapp_stage
docker exec rateapp-postgres createdb -U rateapp -O rateapp_stage rateapp_stage
docker exec -i rateapp-postgres pg_restore -U rateapp --role=rateapp_stage -d rateapp_stage --no-owner --no-acl < "$source_archive"

# Retain the owner's actual library and the Argon2 hash, but no live sessions.
docker exec -i rateapp-postgres psql -U rateapp_stage -d rateapp_stage -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
BEGIN;
DELETE FROM auth_sessions;
DELETE FROM push_subscriptions;
DELETE FROM login_throttles;
DELETE FROM users WHERE nickname <> 'soulbadguy';
DO $$ BEGIN
  IF (SELECT count(*) FROM users WHERE nickname='soulbadguy') <> 1 THEN
    RAISE EXCEPTION 'Owner test account missing';
  END IF;
END $$;
COMMIT;
SQL
printf '%s\n' "$sha" > /srv/rateapp/stage-initialized
echo 'Staging database initialized'
