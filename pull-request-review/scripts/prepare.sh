#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
printf '%s\n' "$REVIEW_RESULTS" \
  | uv run --locked --script "$script_directory/prepare.py" --commit-id "$HEAD_SHA" \
  > "$RUNNER_TEMP/prepared-review.json"

delimiter="review-$(openssl rand -hex 16)"
{
  printf 'result<<%s\n' "$delimiter"
  cat "$RUNNER_TEMP/prepared-review.json"
  printf '%s\n' "$delimiter"
} >> "$GITHUB_OUTPUT"
jq --raw-output '.body' "$RUNNER_TEMP/prepared-review.json" >> "$GITHUB_STEP_SUMMARY"
