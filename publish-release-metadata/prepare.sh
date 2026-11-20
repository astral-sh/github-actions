#!/usr/bin/env bash
set -euo pipefail

if [[ ! "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "::error::Project must be a lowercase name containing only letters, digits, underscores, or hyphens."
  exit 1
fi
if [[ ! "$RELEASE" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ]]; then
  echo "::error::Release must start with a letter or digit and contain only letters, digits, dots, underscores, plus signs, or hyphens."
  exit 1
fi
case "$MERGE_MODE" in
  review|admin-squash) ;;
  *)
    echo "::error::Merge mode must be review or admin-squash."
    exit 1
    ;;
esac
if [[ ! -f "$METADATA_FILE" ]]; then
  echo "::error::The metadata file must be a regular NDJSON file."
  exit 1
fi

# The destination ruleset protects branches matching update-versions-*.
release_hash="$(printf '%s' "$RELEASE" | sha256sum)"
branch="update-versions-$PROJECT-${release_hash:0:20}"
ref="refs/heads/$branch"
repository_url=https://github.com/astral-sh/versions.git
export GIT_TERMINAL_PROMPT=0
remote_ref="$(git -c credential.helper= ls-remote --refs "$repository_url" "$ref")"
expected_head="${remote_ref%%$'\t'*}"

staging_dir="$(mktemp -d "$RUNNER_TEMP/versions-update.XXXXXXXX")"
trap 'rm -rf -- "$staging_dir"' EXIT
data="$staging_dir/versions"
versions_file="v1/$PROJECT.ndjson"

# Fetch executable code independently from the mutable destination checkout.
tooling_commit=e7b64e31fc4f53e6151e8dd7dcb578759d85e24b
tooling_sha256=118eb40349d646cbaeff1f5c756fbff5dc06e7df12646eb51da7a0eb8dc4285b
insert="$staging_dir/insert-versions.py"
curl --proto '=https' --fail --silent --show-error --retry 3 --max-time 30 \
  --output "$insert" \
  "https://raw.githubusercontent.com/astral-sh/versions/$tooling_commit/scripts/insert-versions.py"
checksum_output="$(sha256sum < "$insert")"
if [[ "${checksum_output%% *}" != "$tooling_sha256" ]]; then
  echo "::error::The pinned versions insertion script failed checksum verification."
  exit 1
fi

git -c credential.helper= clone --quiet --depth 1 --no-tags \
  --branch main --single-branch --no-recurse-submodules "$repository_url" "$data"
if [[ ! -d "$data/v1" || -L "$data/v1" || -L "$data/$versions_file" ]] ||
   [[ -e "$data/$versions_file" && ! -f "$data/$versions_file" ]]; then
  echo "::error::The versions checkout has an invalid metadata path."
  exit 1
fi

python3 -I "$insert" --name "$PROJECT" --output "$data/v1" < "$METADATA_FILE"

git -C "$data" add -- "$versions_file"
if git -C "$data" diff --cached --quiet; then
  echo "Release metadata is already up to date."
  echo "changed=false" >> "$GITHUB_OUTPUT"
  exit 0
else
  diff_status=$?
  if [[ "$diff_status" != 1 ]]; then
    exit "$diff_status"
  fi
fi
git -C "$data" diff --cached --check
git -C "$data" -c user.name="astral-releases-bot[bot]" \
  -c user.email="328004183+astral-releases-bot[bot]@users.noreply.github.com" \
  commit --quiet -m "Update $PROJECT to version $RELEASE"

printf 'changed=true\nstaging-dir=%s\nbranch=%s\nexpected-head=%s\n' \
  "$staging_dir" "$branch" "$expected_head" >> "$GITHUB_OUTPUT"
trap - EXIT
