# Create release pull request

Commit prepared changes on `release/<version>` and open a pull request against
the default branch. A rerun from a fresh checkout force-updates the branch and
reuses its same-repository pull request, preserving the title and description.

The caller needs Bash, Git, and the GitHub CLI. Check out the repository at the
workspace root with full history and tags, install the project's tools, and
prepare and validate the release files. Leave the changes uncommitted. Pin the
action to a full commit SHA.

This example assumes a `workflow_dispatch` workflow with a required string input
named `version`. Replace `example/project` and the preparation script with the
caller's repository and release command.

```yaml
jobs:
  prepare:
    if: github.repository == 'example/project' && github.ref == format('refs/heads/{0}', github.event.repository.default_branch)
    runs-on: ubuntu-latest
    timeout-minutes: 30
    concurrency:
      group: release-prepare-${{ inputs.version }}
      cancel-in-progress: false
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false

      - name: Prepare release files
        shell: bash
        env:
          VERSION: ${{ inputs.version }}
        run: ./scripts/prepare-release.sh "$VERSION"

      - uses: astral-sh/github-actions/create-release-pr@<commit-sha>
        id: release-pr
        with:
          version: ${{ inputs.version }}
```

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `version` | Yes | | Version for the branch and `Release <version>` commit message. Can be an output of a preparation step. |
| `tag-prefix` | No | Empty | Prefix for the existing-tag check, such as `v`. |
| `token` | No | `github.token` | Token used to push the branch and create the pull request. |

The action rejects invalid Git refs, an existing local release tag, or no changes
to commit. It stages tracked modifications and deletions, includes already-staged
changes, and leaves untracked files out. It runs `git diff --cached --check`
before committing as `github-actions[bot]`. The repository's Git identity
configuration is not changed.

The `pull-request-url` output contains the created or existing pull request URL.

The default token needs `contents: write`, `pull-requests: write`, and the
repository setting that allows GitHub Actions to create pull requests. To use a
token obtained by an earlier step, pass it as `token` with the same repository
permissions.

The default token does not trigger push workflows. Pull request workflows from
its `opened`, `synchronize`, or `reopened` events require approval from a user
with write access. See
[GitHub's workflow triggering rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
