#!/usr/bin/env bash
# The commit under test must descend from SOURCE_SHA and differ from it only
# under .github/, so every result below is a result for SOURCE_SHA's source tree.
set -euo pipefail
if ! git merge-base --is-ancestor "$SOURCE_SHA" HEAD; then
  echo "HEAD does not descend from $SOURCE_SHA" >&2
  exit 1
fi
changed=$(git diff --name-only "$SOURCE_SHA" HEAD)
printf 'Files that differ from %s:\n%s\n' "$SOURCE_SHA" "$changed"
if printf '%s\n' "$changed" | grep -v '^\.github/'; then
  echo "files outside .github/ differ from $SOURCE_SHA" >&2
  exit 1
fi
echo "Source tree under test: $(git rev-parse "$SOURCE_SHA^{tree}") ($SOURCE_SHA)"
