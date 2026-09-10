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
command_found=false
for binary in "${binary_names[@]}"; do
  if [[ ! "$binary" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ]]; then
    echo "Invalid binary name: $binary" >&2
    exit 1
  fi
  if [[ "$binary" == "$COMMAND" ]]; then command_found=true; fi
done
if [[ "$command_found" != true ]]; then
  echo "The default command must be one of the copied binaries" >&2
  exit 1
fi

dockerfile="$RUNNER_TEMP/docker-variant.Dockerfile"
{
  printf 'FROM %s\nCOPY --from=%s' "$base_image" "$SOURCE_IMAGE"
  printf ' /%s' "${binary_names[@]}"
  printf ' /usr/local/bin/\n'
  if [[ -n "$DOCKERFILE_LINES" ]]; then printf '%s\n' "$DOCKERFILE_LINES"; fi
  printf 'ENTRYPOINT []\nCMD ["/usr/local/bin/%s"]\n' "$COMMAND"
} > "$dockerfile"

{
  echo "name=${image_tags[0]}"
  echo "file=$dockerfile"
  echo "tags<<DOCKER_VARIANT_TAGS"
  # The full version and first alias determine the OCI version label.
  for tag in "${image_tags[@]}"; do
    if [[ "$PUSH_DEV" == true ]]; then
      printf 'type=sha,suffix=-%s\n' "$tag"
    else
      printf 'type=pep440,pattern={{ version }},suffix=-%s,value=%s\n' "$tag" "$VERSION"
      printf 'type=pep440,pattern={{ major }}.{{ minor }},suffix=-%s,value=%s\n' "$tag" "$VERSION"
      printf 'type=raw,value=%s\n' "$tag"
    fi
  done
  echo "DOCKER_VARIANT_TAGS"
} >> "$GITHUB_OUTPUT"
