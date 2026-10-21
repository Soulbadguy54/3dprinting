#!/usr/bin/env bash
set -euo pipefail
test -n "${CRON_SECRET:-}"
secret="$CRON_SECRET"
printf 'url = "http://127.0.0.1:18080/api/cron/release-alerts"\nheader = "Authorization: Bearer %s"\nfail\nsilent\nshow-error\n' "$secret" | curl --config -
