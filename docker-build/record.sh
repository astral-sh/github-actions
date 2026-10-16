#!/usr/bin/env bash
set -euo pipefail

jq -en \
  --arg name "$NAME" \
  --arg build_id "$BUILD_ID" \
  --arg digest "$DIGEST" \
  --arg tags "$TAGS" \
  --arg annotations "$ANNOTATIONS" \
  '{name: $name, build_id: $build_id, digest: $digest,
    tags: ($tags | split("\n")), annotations: ($annotations | split("\n") | map(select(. != "")))}
    | select((.name | test("^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$"))
      and (.build_id | test("^[a-zA-Z0-9]+$"))
      and (.digest | test("^sha256:[0-9a-f]{64}$")))' \
  > "$RUNNER_TEMP/docker-image-record.json"
echo "path=$RUNNER_TEMP/docker-image-record.json" >> "$GITHUB_OUTPUT"
