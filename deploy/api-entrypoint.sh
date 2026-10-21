#!/bin/sh
set -eu
test -r /run/secrets/postgres_password
password=$(cat /run/secrets/postgres_password)
export DATABASE_URL="postgresql+psycopg://rateapp:${password}@${RATEAPP_DB_HOST:-db}:5432/${RATEAPP_DB_NAME:-rateapp}"
unset password POSTGRES_URL NEON_DATABASE_URL
exec "$@"
