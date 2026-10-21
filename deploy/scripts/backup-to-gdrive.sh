#!/usr/bin/env bash
# Autonomous daily PostgreSQL backup. Owner opted for plain Google Drive files.
set -euo pipefail
umask 077
command -v rclone >/dev/null
rclone listremotes | grep -qx 'rateapp-drive:'
db="${RATEAPP_BACKUP_DB:-rateapp}"
[[ "$db" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]] || exit 2
subdir="${RATEAPP_BACKUP_SUBDIR:-}"
[[ "$subdir" =~ ^[a-zA-Z0-9_/-]*$ ]] || exit 2
install -d -m 0700 /srv/rateapp/backups/daily
date_utc="$(date -u +%Y%m%dT%H%M%SZ)"
archive="/srv/rateapp/backups/daily/rateapp-${db}-${date_utc}.dump"
remote_dir="rateapp-drive:RateApp/backups"
[[ -z "$subdir" ]] || remote_dir="$remote_dir/$subdir"
trap 'rm -f "$archive.partial"' EXIT
docker exec rateapp-postgres pg_dump -U rateapp -d "$db" -Fc > "$archive.partial"
test -s "$archive.partial"
docker exec -i rateapp-postgres pg_restore --list < "$archive.partial" >/dev/null
mv "$archive.partial" "$archive"
chmod 0600 "$archive"
remote_file="$remote_dir/$(basename "$archive")"
rclone copyto "$archive" "$remote_file" --retries 3
local_hash="$(sha256sum "$archive" | cut -d' ' -f1)"
remote_hash="$(rclone cat "$remote_file" | sha256sum | cut -d' ' -f1)"
test "$local_hash" = "$remote_hash"
echo "Google Drive PostgreSQL backup uploaded and verified: $(basename "$archive")"
# Intentionally no remote deletion; retention will be reviewed after monitoring.
