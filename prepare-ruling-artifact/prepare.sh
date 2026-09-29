#!/usr/bin/env bash
set -euo pipefail

if [[ ! "$ARTIFACT_NAME" =~ ^actual_[a-zA-Z0-9_.-]+$ ]]; then
  echo "::error::artifact-name must begin with actual_ and contain only letters, numbers, _, ., or -" >&2
  exit 1
fi

actual_root="$ACTUAL_ROOT"
if [ -z "$actual_root" ]; then
  if [ -d its/ruling/target/actual ] && [ -d private/its/ruling/target/actual ]; then
    echo "::error::Both supported generated ruling directories exist; set actual-root" >&2
    exit 1
  elif [ -d its/ruling/target/actual ]; then
    actual_root=its/ruling/target/actual
  elif [ -d private/its/ruling/target/actual ]; then
    actual_root=private/its/ruling/target/actual
  else
    echo "::error::No generated ruling directory found; set actual-root" >&2
    exit 1
  fi
fi

if [ ! -d "$actual_root" ] || [ -z "$(find "$actual_root" -type f -name '*.json' -print -quit)" ]; then
  echo "::error::No generated ruling JSON files found in $actual_root" >&2
  exit 1
fi

stage_root="$(mktemp -d "$RUNNER_TEMP/ruling-artifact.XXXXXX")"
mkdir -p "$stage_root/expected"
cp -R -- "$actual_root/." "$stage_root/expected/"
printf 'path=%s\n' "$stage_root" >> "$GITHUB_OUTPUT"
