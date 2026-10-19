#!/usr/bin/env bash
# Vercel Ignored Build Step: exit 0 = SKIP build, exit 1 = BUILD.
# Only documentation changes can be skipped. Unknown conditions fail open.
set -u

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Build: no Git checkout available."
  exit 1
fi

# Unlike HEAD^, the last successful deployment protects against hiding earlier
# code commits under a later docs-only commit. Vercel usually exposes this SHA.
if [[ -n "${VERCEL_GIT_PREVIOUS_SHA:-}" ]]; then
  base="$VERCEL_GIT_PREVIOUS_SHA"
  if ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
    echo "Build: last successful deployment commit is unavailable in shallow clone."
    exit 1
  fi
else
  # First deployment/preview: compare the immediate parent if possible.
  # If none exists, build rather than risk skipping application code.
  if ! git rev-parse HEAD^ >/dev/null 2>&1; then
    echo "Build: no previous commit to compare."
    exit 1
  fi
  base="HEAD^"
fi

if ! changed="$(git diff --no-ext-diff --no-renames --name-only "$base" HEAD --)"; then
  echo "Build: Git diff failed."
  exit 1
fi
if [[ -z "$changed" ]]; then
  echo "Build: no changed paths; allow explicit/manual redeploys."
  exit 1
fi

while IFS= read -r path; do
  case "$path" in
    AGENTS.md|CHANGELOG.md|README.md|docs/*.md)
      ;;
    *)
      echo "Build: application/config path changed: $path"
      exit 1
      ;;
  esac
done <<< "$changed"

echo "Skip: only repository Markdown documentation changed."
exit 0
