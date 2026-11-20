#!/usr/bin/env bash
set -euo pipefail

trap 'rm -rf -- "$STAGING_DIR"' EXIT
if [[ -z "$GH_TOKEN" ]]; then
  echo "::error::A token scoped to astral-sh/versions is required."
  exit 1
fi

repository=astral-sh/versions
ref="refs/heads/$BRANCH"
cd "$STAGING_DIR/versions"

remote_git() {
  git -c credential.helper= -c 'credential.helper=!gh auth git-credential' "$@"
}

published_head="$(git rev-parse HEAD)"
current_tree="$(git rev-parse 'HEAD^{tree}')"
base_commit="$(git rev-parse 'HEAD^')"
remote_commit=
if [[ -n "$EXPECTED_HEAD" ]]; then
  remote_git fetch --quiet --no-tags --depth 1 origin "$ref"
  if [[ "$(git rev-parse FETCH_HEAD)" != "$EXPECTED_HEAD" ]]; then
    echo "::error::The versions update branch changed while preparing to publish. Rerun the job."
    exit 1
  fi
  remote_commit="$(git cat-file commit FETCH_HEAD)"
fi

if [[ "$remote_commit" == "tree $current_tree"$'\n'"parent $base_commit"$'\n'* ]]; then
  published_head="$EXPECTED_HEAD"
else
  remote_git push --no-follow-tags --force-with-lease="$ref:$EXPECTED_HEAD" \
    origin "HEAD:$ref"
fi

find_pull_request() {
  gh pr list --repo "$repository" --base main --head "$BRANCH" --state open \
    --json url,isCrossRepository --jq 'map(select(.isCrossRepository == false))[0].url // empty'
}

pull_request="$(find_pull_request)"
if [[ -z "$pull_request" ]]; then
  if ! pull_request="$(gh pr create --repo "$repository" --base main --head "$BRANCH" \
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
  # After a push GitHub may still report the previous head or unknown mergeability.
  for ((attempt = 0; attempt < 6; attempt++)); do
    status="$(gh pr view --repo "$repository" "$pull_request" \
      --json headRefOid,mergeable,state --jq '[.headRefOid, .mergeable, .state] | @tsv')"
    IFS=$'\t' read -r pull_head mergeable state <<< "$status"
    if [[ "$pull_head" == "$published_head" ]]; then
      if [[ "$state" == MERGED ]]; then
        exit 0
      fi
      if [[ "$mergeable" != UNKNOWN ]]; then
        gh pr merge --repo "$repository" "$pull_request" --squash --admin \
          --match-head-commit "$published_head"
        exit 0
      fi
    fi
    if [[ "$attempt" != 5 ]]; then
      sleep 2
    fi
  done
  echo "::error::GitHub did not report mergeability for the published commit. Rerun the job."
  exit 1
fi
