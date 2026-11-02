#!/usr/bin/env bash
# The commit under test must be SOURCE_SHA plus files under .github/ only, so
# every result below is a result for SOURCE_SHA's source tree.
set -euo pipefail
parent=$(git rev-parse HEAD^)
if [ "$parent" != "$SOURCE_SHA" ]; then
  echo "parent is $parent, expected $SOURCE_SHA" >&2
  exit 1
fi
changed=$(git diff --name-only "$SOURCE_SHA" HEAD)
printf 'Files this commit adds on top of %s:\n%s\n' "$SOURCE_SHA" "$changed"
if printf '%s\n' "$changed" | grep -v '^\.github/'; then
  echo "files outside .github/ differ from $SOURCE_SHA" >&2
  exit 1
fi
echo "Source tree under test: $(git rev-parse "$SOURCE_SHA^{tree}") ($SOURCE_SHA)"
