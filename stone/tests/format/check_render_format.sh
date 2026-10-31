#!/usr/bin/env bash
# Check that `stone render` writes files that Prettier accepts (#224).
# For each config in this folder, render into a temp git repo, then run `prettier --check .`.
# The hand-written config is in .prettierignore. Exit non-zero if any config fails.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
PRETTIER="prettier@3.9.10"
failed=()

for config in "$HERE"/*.yaml; do
  name="$(basename "$config")"
  tmp="$(mktemp -d)"
  echo "== $name"
  # set -e does not apply inside an `if ( ... )` subshell, so each step ends with `|| exit 1`.
  if (
    cd "$tmp" || exit 1
    git init -q || exit 1
    mkdir .cornerstone || exit 1
    cp "$config" .cornerstone/config.yaml || exit 1
    stone render --root "$tmp" --framework "$REPO/framework" || exit 1
    printf '%s\n' ".cornerstone/config.yaml" > .prettierignore || exit 1
    npx --yes "$PRETTIER" --check . || exit 1
  ); then
    echo "ok: $name"
  else
    echo "FAILED: $name" >&2
    failed+=("$name")
  fi
  rm -rf "$tmp"
done

if [ "${#failed[@]}" -gt 0 ]; then
  echo "Prettier check failed for: ${failed[*]}" >&2
  exit 1
fi
echo "All configs pass."
