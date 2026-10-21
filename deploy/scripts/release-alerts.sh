#!/usr/bin/env bash
set -euo pipefail
test -s /srv/rateapp/secrets/cron_secret
secret="$(cat /srv/rateapp/secrets/cron_secret)"
printf 'url = "http://127.0.0.1:18080/api/cron/release-alerts"\nheader = "Authorization: Bearer %s"\nfail\nsilent\nshow-error\n' "$secret" | curl --config -
