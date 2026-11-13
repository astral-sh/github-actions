#!/usr/bin/env bash
set -euo pipefail

IFS=',' read -r base_image aliases <<< "$IMAGE_MAPPING"
if [[ -z "$base_image" || -z "$aliases" || -z "$SOURCE_IMAGE" || "$base_image$SOURCE_IMAGE" == *[$'\n\r\t ']* ]]; then
  echo "Expected a base image and at least one image alias" >&2
  exit 1
fi
IFS=',' read -r -a image_tags <<< "$aliases"
for tag in "${image_tags[@]}"; do
  if [[ ! "$tag" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ]]; then
    echo "Invalid image alias: $tag" >&2
    exit 1
  fi
done

read -r -a binary_names <<< "$BINARIES"
if [[ ${#binary_names[@]} -eq 0 ]]; then
  echo "At least one binary name is required" >&2
  exit 1
fi
for binary in "${binary_names[@]}"; do
  if [[ ! "$binary" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ]]; then
    echo "Invalid binary name: $binary" >&2
    exit 1
  fi
done

dockerfile="$RUNNER_TEMP/docker-variant.Dockerfile"
{
  printf 'FROM %s\nCOPY --from=%s' "$base_image" "$SOURCE_IMAGE"
  printf ' /%s' "${binary_names[@]}"
  printf ' /usr/local/bin/\n'
  if [[ -n "$DOCKERFILE_LINES" ]]; then printf '%s\n' "$DOCKERFILE_LINES"; fi
  printf 'ENTRYPOINT []\nCMD ["/usr/local/bin/%s"]\n' "${binary_names[0]}"
} > "$dockerfile"

{
  echo "name=${image_tags[0]}"
  echo "file=$dockerfile"
  echo "aliases<<DOCKER_VARIANT_ALIASES"
  printf '%s\n' "${image_tags[@]}"
  echo "DOCKER_VARIANT_ALIASES"
} >> "$GITHUB_OUTPUT"
