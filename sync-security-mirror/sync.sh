#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf '::error::%s\n' "$1" >&2
    exit 1
}

is_repository() {
    [[ "$1" =~ ^[a-zA-Z0-9-]+/[a-zA-Z0-9._-]+$ && "$1" != */. && "$1" != */.. ]]
}

is_repository "$SOURCE_REPOSITORY" || fail "Expected a source repository in owner/name form."
is_repository "$DESTINATION_REPOSITORY" || fail "Expected a destination repository in owner/name form."
[[ "${SOURCE_REPOSITORY,,}" != "${DESTINATION_REPOSITORY,,}" ]] || fail "The source and destination repositories must differ."
[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "Expected a full public commit SHA."
[[ -n "$DESTINATION_TOKEN" ]] || fail "Expected a scoped destination token."

destination_token=$DESTINATION_TOKEN
unset DESTINATION_TOKEN GH_TOKEN GITHUB_TOKEN

# Use a fresh repository and disable inherited configuration, credentials, and
# object stores. The public clone must succeed without the mirror token.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_COUNT=0
export GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false
unset GIT_CONFIG_PARAMETERS GIT_DIR GIT_COMMON_DIR GIT_WORK_TREE
unset GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES

temp_directory=$(mktemp -d "$RUNNER_TEMP/security-mirror.XXXXXXXX")
trap 'rm -rf -- "$temp_directory"' EXIT
sync_repository="$temp_directory/source.git"
source_url="https://github.com/$SOURCE_REPOSITORY.git"
destination_url="https://github.com/$DESTINATION_REPOSITORY.git"

# Suppress libcurl-generated Authorization headers even when a .netrc is present.
git -C "$temp_directory" -c http.extraHeader=Authorization: clone \
    --quiet --bare --single-branch --branch main \
    --no-tags --no-recurse-submodules --template='' "$source_url" "$sync_repository"
if [[ "$(git -C "$sync_repository" cat-file -t "$SOURCE_SHA" 2>/dev/null)" != commit ]] ||
    ! git -C "$sync_repository" merge-base --is-ancestor "$SOURCE_SHA" refs/heads/main; then
    fail "The requested commit is not on public main."
fi

destination_git() {
    GH_TOKEN="$destination_token" GH_HOST=github.com git -C "$sync_repository" \
        -c credential.helper= -c 'credential.helper=!gh auth git-credential' "$@"
}

# Read the destination ref without downloading objects or exposing remote output.
if ! destination_main=$(destination_git ls-remote --exit-code --refs "$destination_url" refs/heads/main 2>/dev/null); then
    fail "Could not read the destination main branch."
fi
destination_sha="${destination_main%%$'\t'*}"
if [[ ! "$destination_sha" =~ ^[0-9a-f]{40}$ ||
    "$destination_main" != "$destination_sha"$'\t'refs/heads/main ]]; then
    fail "Unexpected destination main ref."
fi

if [[ "$(git -C "$sync_repository" cat-file -t "$destination_sha" 2>/dev/null)" != commit ]] ||
    ! git -C "$sync_repository" merge-base --is-ancestor "$destination_sha" refs/heads/main 2>/dev/null; then
    fail "Destination main is not on public main. Refusing to sync."
fi
if git -C "$sync_repository" merge-base --is-ancestor "$SOURCE_SHA" "$destination_sha"; then
    echo "Destination main already contains the requested public commit."
    exit 0
fi
if ! git -C "$sync_repository" merge-base --is-ancestor "$destination_sha" "$SOURCE_SHA"; then
    fail "Destination main has diverged from the requested public commit. Refusing to sync."
fi

if ! destination_git push --quiet --no-force --no-follow-tags \
    "$destination_url" "$SOURCE_SHA:refs/heads/main" >/dev/null 2>&1; then
    fail "Could not fast-forward destination main."
fi
echo "Synced destination main to the requested public commit."
