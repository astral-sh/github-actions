#!/usr/bin/env bash
set -euo pipefail

trap 'rm -rf -- "$STAGING_DIR"' EXIT
if [[ -z "$GH_TOKEN" ]]; then
  echo "::error::A token scoped to astral-sh/versions is required."
  exit 1
fi

repository=astral-sh/versions
branch="update-versions/$PROJECT/$RELEASE"
ref="refs/heads/$branch"
cd "$STAGING_DIR/versions"

remote_git() {
  git -c credential.helper= -c 'credential.helper=!gh auth git-credential' "$@"
}

remote_ref="$(remote_git ls-remote --refs origin "$ref")"
expected_head="${remote_ref%%$'\t'*}"
published_head="$(git rev-parse HEAD)"
current_tree="$(git rev-parse 'HEAD^{tree}')"
remote_tree=
if [[ -n "$expected_head" ]]; then
  remote_git fetch --quiet --no-tags --depth 1 origin "$ref"
  if [[ "$(git rev-parse FETCH_HEAD)" != "$expected_head" ]]; then
    echo "::error::The versions update branch changed while preparing to publish. Rerun the job."
    exit 1
  fi
  remote_tree="$(git rev-parse 'FETCH_HEAD^{tree}')"
fi

if [[ "$remote_tree" == "$current_tree" ]]; then
  published_head="$expected_head"
else
  remote_git push --no-follow-tags --force-with-lease="$ref:$expected_head" \
    origin "HEAD:$ref"
fi

find_pull_request() {
  gh pr list --repo "$repository" --base main --head "$branch" --state open \
    --json url,isCrossRepository --jq 'map(select(.isCrossRepository == false))[0].url // empty'
}

pull_request="$(find_pull_request)"
if [[ -z "$pull_request" ]]; then
  if ! pull_request="$(gh pr create --repo "$repository" --base main --head "$branch" \
    --title "Add $PROJECT $RELEASE" --body "Automated versions update for $PROJECT $RELEASE." \
    --label automation)"; then
    # Another run may have opened the pull request for this branch.
    pull_request="$(find_pull_request)"
    if [[ -z "$pull_request" ]]; then
      exit 1
    fi
  fi
fi

printf 'pull-request-url=%s\n' "$pull_request" >> "$GITHUB_OUTPUT"
if [[ "$MERGE_MODE" == admin-squash ]]; then
  gh pr merge --repo "$repository" "$pull_request" --squash --admin \
    --match-head-commit "$published_head"
fi
