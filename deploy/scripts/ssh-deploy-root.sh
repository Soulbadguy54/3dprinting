#!/usr/bin/env bash
# Root-only one-time installed dispatcher; also constrains releases to the current main history.
set -euo pipefail
sha="${1:?commit required}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
cd /srv/rateapp/source
git fetch -q origin main
git fetch -q origin "$sha"
git merge-base --is-ancestor "$sha" origin/main || { echo "Refusing commit outside main" >&2; exit 3; }
git checkout -q --detach "$sha"
exec bash deploy/scripts/deploy.sh "$sha"
