# Publish built documentation

Replace a project's subtree in `astral-sh/docs` and open or reuse a pull request against `main`. Call it after building the site on a runner with Python 3.10 or newer, Git, and the GitHub CLI.

| Input | Description |
| --- | --- |
| `source-directory` | Built directory under the caller's workspace. It must contain at least one file. |
| `destination` | Project subtree in the form `site/<project>`, where the project uses lowercase letters, digits, and hyphens. Every file under this subtree is replaced by the new build. |
| `publication-key` | Stable identifier for a logical update, such as a release tag or a preview ref. Use the same key on retries and separate keys for release and preview updates. |
| `title` | Title for a new pull request. |
| `body` | Description for a new pull request. Defaults to `Automated documentation update.` |
| `token` | GitHub token scoped to `astral-sh/docs` with `contents: write` and `pull_requests: write`. |
| `merge-policy` | `review` leaves the PR open and is the default. `squash-admin` requests an immediate admin squash merge of the exact commit published by the action. Use it in a caller's already approved release path with a token authorized to bypass the repository's rules. |

Outputs are `changed` and `pull-request-url`. An identical site on `main` returns `false` and an empty URL. When there are changes, the action adds the `documentation` label and reuses the open PR for that destination and publication key. Subsequent updates preserve the PR title and description. A Git lease rejects overwriting a branch that another run changed during publication. Callers should serialize updates to the same project site when publishing order matters.

## Example

Run this in the caller's docs publishing job after building the site. Use the same pinned commit for both shared actions.

```yaml
- name: Get docs token
  id: docs-token
  uses: astral-sh/github-actions/simple-token-service@<commit-sha>
  with:
    exchange-url: ${{ secrets.RELEASES_STS_API_URL }}/exchange
    audience: ${{ secrets.RELEASES_STS_API_URL }}
    repository: astral-sh/docs
    permissions: |
      contents: write
      pull_requests: write

- name: Open docs pull request
  uses: astral-sh/github-actions/publish-docs@<commit-sha>
  with:
    source-directory: site/uv
    destination: site/uv
    publication-key: preview-${{ github.sha }}
    title: Update uv documentation
    token: ${{ steps.docs-token.outputs.token }}
    merge-policy: review
```

The uv, Ruff, and ty callers can pass `squash-admin` for their explicit release plans and use `review` for manual or implicit-tag builds. Python Build Standalone can use the default `review` policy. The docs index overlays several paths at the site root. Migrating it needs an explicit mapping of the paths it owns.
