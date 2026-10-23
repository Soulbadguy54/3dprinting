#!/usr/bin/env bash
# Installed root-only from main. Executes only reviewed staging actions.
set -euo pipefail
mode="${1:?mode required}"
sha="${2:?SHA required}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || exit 2
cd /srv/rateapp/source
case "$mode" in
  bootstrap)
    test "$sha" = "$(cat /srv/rateapp/current-release)"
    exec bash deploy/scripts/bootstrap-stage.sh "$sha"
    ;;
  deploy)
    git fetch -q origin +refs/heads/develop:refs/remotes/origin/develop
    test "$(git rev-parse refs/remotes/origin/develop)" = "$sha" || {
      echo 'Refusing a non-current develop commit' >&2
      exit 3
    }
    exec bash deploy/scripts/deploy-stage.sh "$sha"
    ;;
  *)
    echo 'Unsupported staging operation' >&2
    exit 64
    ;;
esac
