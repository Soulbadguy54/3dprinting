#!/bin/sh
set -eu
password_file="${RATEAPP_DB_PASSWORD_FILE:-/run/secrets/postgres_password}"
test -r "$password_file"
password=$(cat "$password_file")
export DATABASE_URL="postgresql+psycopg://${RATEAPP_DB_USER:-rateapp}:${password}@${RATEAPP_DB_HOST:-db}:5432/${RATEAPP_DB_NAME:-rateapp}"
unset password POSTGRES_URL NEON_DATABASE_URL
exec "$@"
