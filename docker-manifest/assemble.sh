#!/usr/bin/env bash
set -euo pipefail

# Require exactly the expected names, not only the expected number of records.
# The first alias in each mapping is its manifest record name.
jq -se --arg base "$BASE_NAME" --argjson mappings "$IMAGE_MAPPINGS" '
  ([$base] + ($mappings | map(split(",")[1]))) as $expected
  | if ($expected | unique | length) != ($expected | length)
      or (map(.name) | sort) != ($expected | sort)
    then error("incomplete Docker image manifest")
    else {base: map(select(.name == $base))[0],
          extra: map(select(.name != $base))}
    end
' "$RECORDS_PATH"/*/*.json > "$RUNNER_TEMP/docker-manifest.json"
echo "path=$RUNNER_TEMP/docker-manifest.json" >> "$GITHUB_OUTPUT"
