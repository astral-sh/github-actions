# Sync a security mirror

Fast-forward a GitHub security mirror's existing `main` branch to a commit on
the public source repository's `main`. This composite action runs on Linux and
requires Bash, Git, and the GitHub CLI.

The action builds a temporary bare clone from public `main` and uses a scoped
token to read and update the mirror's `main` ref. It checks both commits against
public history before it pushes. If the mirror already contains the requested
commit, the action succeeds without pushing. A missing or divergent mirror ref
fails the job. The action suppresses destination Git diagnostics to avoid
exposing private refs in workflow logs.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `source-repository` | No | `github.repository` | Public GitHub repository in `owner/name` form. |
| `source-sha` | No | `github.sha` | Full lowercase commit SHA on public `main`. |
| `destination-repository` | Yes | | GitHub security mirror in `owner/name` form with an existing `main`. |
| `token` | Yes | | GitHub App installation token scoped to the mirror. Request `contents: write` and `workflows: write` to sync changes that touch workflow files. |

The caller controls triggers, job permissions, and token issuance. This
example uses the existing [token service](../simple-token-service/) and runs
only on the trusted source branch. Replace `<commit-sha>` with a full commit
SHA that contains both actions.

```yaml
name: Sync Ruff security mirror

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions: {}

concurrency:
  group: sync-ruff-security-main
  cancel-in-progress: false

jobs:
  sync:
    if: github.repository == 'astral-sh/ruff' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment:
      name: automations
      deployment: false
    permissions:
      id-token: write
    steps:
      - uses: astral-sh/github-actions/simple-token-service@<commit-sha>
        id: token
        with:
          exchange-url: ${{ secrets.STS_API_URL }}/exchange
          audience: ${{ secrets.STS_API_URL }}
          repository: astral-sh/ruff-security
          permissions: |
            contents: write
            workflows: write

      - uses: astral-sh/github-actions/sync-security-mirror@<commit-sha>
        with:
          destination-repository: astral-sh/ruff-security
          token: ${{ steps.token.outputs.token }}
```
