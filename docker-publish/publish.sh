#!/usr/bin/env bash
set -euo pipefail

build_id=$(jq -er '.build_id | select(test("^[a-zA-Z0-9]+$"))' <<< "$IMAGE_JSON")
digest=$(jq -er '.digest | select(test("^sha256:[0-9a-f]{64}$"))' <<< "$IMAGE_JSON")

# Registry credentials and the destination allowlist belong to the calling
# publishing workflow, not to the build artifact.
destinations=$(jq -Ren --arg images "$IMAGES" '$images | split("\n") | map(select(. != ""))')
jq -e --argjson destinations "$destinations" --arg attestation_image "$ATTESTATION_IMAGE" '
  . as $record
  | ($destinations | length) > 0
  and ($destinations | unique | length) == ($destinations | length)
  and ($destinations | index($attestation_image)) != null
  and all($destinations[]; test("^[a-z0-9][a-z0-9./:_-]*[a-z0-9]$"))
  and (.tags | type == "array")
  and all(.tags[]; . as $tag | any($destinations[];
    . as $image | ($tag | startswith($image + ":"))
      and ($tag | ltrimstr($image + ":") | test("^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$"))))
  and all($destinations[]; . as $image | any($record.tags[]; startswith($image + ":")))
  and (.annotations | type == "array")
  and all(.annotations[]; type == "string" and (contains("\n") | not))
' <<< "$IMAGE_JSON" > /dev/null

# Verify that the Depot build ID resolves to the recorded index digest.
token="$(depot pull-token --project "$DEPOT_PROJECT_ID" "$build_id")"
echo "::add-mask::$token"
printf '%s' "$token" | docker login registry.depot.dev --username x-token --password-stdin
saved_digest=$(docker buildx imagetools inspect \
  "registry.depot.dev/${DEPOT_PROJECT_ID}:$build_id" --format '{{.Manifest.Digest}}')
if [[ "$saved_digest" != "$digest" ]]; then
  echo "The saved Depot image does not match the build manifest" >&2
  exit 1
fi

# Keep annotation values containing spaces or shell-special characters together.
annotations=()
while IFS= read -r annotation; do
  annotations+=(--annotation "$annotation")
done < <(jq -r '.annotations[]' <<< "$IMAGE_JSON")

while IFS= read -r image; do
  readarray -t image_tags < <(
    jq -r --arg prefix "$image:" '.tags[] | select(startswith($prefix))' <<< "$IMAGE_JSON"
  )

  # Copy the complete index without loading it through the local image store,
  # which can drop platforms or change the manifest format (astral-sh/uv#14165).
  depot push --project "$DEPOT_PROJECT_ID" --tag "${image_tags[0]}" "$build_id"
  copied_digest=$(docker buildx imagetools inspect \
    "${image_tags[0]}" --format '{{.Manifest.Digest}}')
  if [[ "$copied_digest" != "$digest" ]]; then
    echo "The copied image digest does not match the build manifest" >&2
    exit 1
  fi

  tags=()
  for tag in "${image_tags[@]}"; do tags+=(-t "$tag"); done
  docker buildx imagetools create \
    "${annotations[@]}" \
    "${tags[@]}" \
    --metadata-file "$RUNNER_TEMP/docker-publish-metadata.json" \
    "$image@$digest"

  if [[ "$image" == "$ATTESTATION_IMAGE" ]]; then
    final_digest=$(jq -er '."containerimage.descriptor".digest | select(test("^sha256:[0-9a-f]{64}$"))' \
      "$RUNNER_TEMP/docker-publish-metadata.json")
    echo "digest=$final_digest" >> "$GITHUB_OUTPUT"
  fi
done < <(jq -r '.[]' <<< "$destinations")
