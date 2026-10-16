#!/usr/bin/env bash
set -euo pipefail

: "${HEAD_SHA:?Pull request head SHA is required}"

if [ -n "${REVIEW_RESULT:-}" ]; then
  if [ -n "${REVIEW_RESULTS:-}" ]; then
    echo "Set only one of REVIEW_RESULT or REVIEW_RESULTS." >&2
    exit 1
  fi
  REVIEW_RESULTS="$(jq --null-input --arg result "$REVIEW_RESULT" \
    '{Review: {result: "success", outputs: {result: $result}}}')"
fi
: "${REVIEW_RESULTS:?Review results are required}"

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
