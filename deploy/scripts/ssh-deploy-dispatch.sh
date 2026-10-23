#!/usr/bin/env bash
# Forced-command SSH entrypoint: no interactive shell, port forwarding or arbitrary commands.
set -euo pipefail
command="${SSH_ORIGINAL_COMMAND:-}"
if [[ "$command" =~ ^deploy[[:space:]]([0-9a-f]{40})$ ]]; then
  exec sudo -n /usr/local/sbin/rateapp-deploy-root "${BASH_REMATCH[1]}"
fi
if [[ "$command" =~ ^(bootstrap-stage|deploy-stage)[[:space:]]([0-9a-f]{40})$ ]]; then
  action="${BASH_REMATCH[1]}"
  sha="${BASH_REMATCH[2]}"
  if [[ "$action" == bootstrap-stage ]]; then
    exec sudo -n /usr/local/sbin/rateapp-stage-deploy-root bootstrap "$sha"
  fi
  exec sudo -n /usr/local/sbin/rateapp-stage-deploy-root deploy "$sha"
fi
echo "Only deploy, bootstrap-stage or deploy-stage with exact git SHA is allowed" >&2
exit 64
