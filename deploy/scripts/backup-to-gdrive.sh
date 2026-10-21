#!/usr/bin/env bash
# The server runs this from its own systemd timer; no ChatGPT/Gateway dependency.
# Configure an rclone 'crypt' remote named rateapp-crypt, backed by Google Drive.
set -euo pipefail
umask 077
command -v rclone >/dev/null || { echo 'rclone not installed' >&2; exit 1; }
rclone listremotes | grep -qx 'rateapp-crypt:' || { echo 'Encrypted rclone remote not configured' >&2; exit 1; }
install -d -m 0700 /srv/rateapp/backups/daily
date_utc="$(date -u +%Y%m%dT%H%M%SZ)"
archive="/srv/rateapp/backups/daily/rateapp-$date_utc.dump"
trap 'rm -f "$archive.partial"' EXIT
docker exec rateapp-postgres pg_dump -U rateapp -d rateapp -Fc > "$archive.partial"
test -s "$archive.partial"
docker exec -i rateapp-postgres pg_restore --list < "$archive.partial" >/dev/null
mv "$archive.partial" "$archive"
chmod 600 "$archive"
rclone copyto "$archive" "rateapp-crypt:RateApp/backups/$(basename "$archive")" --retries 3
rclone lsf "rateapp-crypt:RateApp/backups/" --files-only | grep -Fxq "$(basename "$archive")"
echo "Encrypted Google Drive backup uploaded: $(basename "$archive")"
# Retention/deletion is intentionally NOT automated until explicitly reviewed.
