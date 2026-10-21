#!/usr/bin/env bash
# Forced-command SSH entrypoint: no interactive shell, port forwarding or arbitrary commands.
set -euo pipefail
command="${SSH_ORIGINAL_COMMAND:-}"
if [[ "$command" =~ ^deploy[[:space:]]([0-9a-f]{40})$ ]]; then
  exec sudo -n /usr/local/sbin/rateapp-deploy-root "${BASH_REMATCH[1]}"
fi
echo "Only the deploy command with an exact git SHA is allowed" >&2
exit 64
