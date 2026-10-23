#!/usr/bin/env bash
set -euo pipefail
cd /srv/rateapp/staging-source
export RATEAPP_STAGE_RELEASE="${1:?stage SHA required}"
docker compose -f deploy/compose.stage.yaml pull api web
docker compose -f deploy/compose.stage.yaml up -d api web
