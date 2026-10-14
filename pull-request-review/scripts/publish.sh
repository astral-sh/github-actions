#!/usr/bin/env bash
set -euo pipefail

: "${HEAD_SHA:?Pull request head SHA is required}"
: "${PULL_REQUEST_NUMBER:?Pull request number is required}"
: "${GITHUB_REPOSITORY:?Repository is required}"
: "${REVIEW_RESULT:?Prepared review findings are required}"

printf '%s\n' "$REVIEW_RESULT" > "$RUNNER_TEMP/review.json"

if jq --exit-status '.comments | length == 0' "$RUNNER_TEMP/review.json" > /dev/null; then
  echo "No actionable findings to publish."
  exit 0
fi

current_head_sha="$(
  gh pr view "$PULL_REQUEST_NUMBER" \
    --repo "$GITHUB_REPOSITORY" \
    --json headRefOid \
    --jq '.headRefOid'
)"
if [ "$current_head_sha" != "$HEAD_SHA" ]; then
  echo "The pull request head changed; skipping stale review findings."
  exit 0
fi

jq --compact-output '.comments[]' "$RUNNER_TEMP/review.json" |
while IFS= read -r comment; do
  printf '%s\n' "$comment" |
    gh api \
      --method POST \
      "repos/$GITHUB_REPOSITORY/pulls/$PULL_REQUEST_NUMBER/comments" \
      --input - \
      --silent
done
