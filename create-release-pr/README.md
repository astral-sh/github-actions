# Create release pull request

Commit prepared release files on `release/<version>` and create or update a pull
request targeting the repository's default branch. The caller owns checkout,
tool installation, version selection, and preparation and validation of release
files. This composite action handles the release branch, commit, and pull request.

## Usage

Use a runner with Bash, Git, and the GitHub CLI. Check out the caller repository
at the workspace root with full history and tags, and leave prepared changes
uncommitted. Pin the action to a full commit SHA.

```yaml
name: Prepare release

on:
  workflow_dispatch:
    inputs:
      version:
        description: Version to release
        required: true
        type: string

permissions: {}

jobs:
  prepare:
    # Replace the repository name with the intended release repository.
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

      # Add the project's tool setup steps here.

      - name: Prepare release files
        shell: bash
        env:
          VERSION: ${{ inputs.version }}
        # Replace with the project's preparation and validation commands.
        run: ./scripts/prepare-release.sh "$VERSION"

      - uses: astral-sh/github-actions/create-release-pr@<commit-sha>
        id: release-pr
        with:
          version: ${{ inputs.version }}
```

The caller controls the trigger, repository and branch restrictions, runner,
permissions, and concurrency. Preparation steps can use ordinary action `uses`,
`run`, `env`, and step outputs. For example, a caller can derive the release
version during preparation and pass that step's output as `version`.

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `version` | Yes | | Version used in `release/<version>` and the `Release <version>` commit message. |
| `tag-prefix` | No | Empty | Prefix for the existing-tag check, such as `v`. |
| `token` | No | `github.token` | Token used to push the branch and create the pull request. |

The action checks that the version and tag prefix form valid Git refs and rejects
an existing local release tag. Project-specific version syntax and metadata
validation belong in the caller's preparation steps.

The action stages all modifications and deletions to tracked files and includes
any already-staged changes. Untracked files are not added. It fails if there are
no changes to commit. It commits as
`github-actions[bot]` without changing the repository's Git identity configuration.
Re-running from a fresh checkout force-updates the release branch and reuses its
open pull request. Existing pull request titles and descriptions are preserved.

The `pull-request-url` output contains the created or existing pull request URL.

## Authentication

The token needs `contents: write` and `pull-requests: write` on the caller
repository. The default token also requires the repository setting that allows
GitHub Actions to create pull requests. Pass `token` to use credentials obtained
by an earlier step, such as a GitHub App installation token.

Pushes with the default `GITHUB_TOKEN` do not trigger push workflows. Pull request
workflows created by its `opened`, `synchronize`, or `reopened` events require
approval from a user with write access. See
[GitHub's workflow triggering rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
