# Publish release metadata

Use this action to update `v1/<project>.ndjson` in [astral-sh/versions](https://github.com/astral-sh/versions). It runs the registry's pinned insertion script to validate and merge prepared NDJSON, then opens or updates a pull request. An update already present on `main` exits successfully without creating a pull request.

Run on a Linux runner with Bash, Git, GitHub CLI, curl, sha256sum, and Python 3.12 or newer. Prepare the NDJSON using the project's existing generator. For uv, Ruff, and ty, generate it from the cargo-dist plan using a reviewed revision of `convert-cargo-dist-plan.py`. Python Build Standalone can pass the NDJSON it already generates. Keep release approval in the caller's job and grant the job `id-token: write`. The [token service](../simple-token-service/) policy must authorize that workflow to request a release bot installation token for `astral-sh/versions` with `contents: write` and `pull_requests: write`. The release bot needs permission to update the protected `update-versions-*` branches. Pin the action to a commit SHA.

```yaml
- name: Publish metadata
  id: versions
  uses: astral-sh/github-actions/publish-release-metadata@<commit-sha>
  with:
    project: uv
    release: ${{ steps.release.outputs.version }}
    metadata-file: dist/versions.ndjson
    sts-api-url: ${{ secrets.RELEASES_STS_API_URL }}
```

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `project` | Yes | | Lowercase project name used for the versions filename. |
| `release` | Yes | | Release identifier used for the update branch and PR. For Python Build Standalone this can be the build date tag even when the file contains multiple Python versions. |
| `metadata-file` | Yes | | Path to a prepared NDJSON file. Relative paths are resolved from the caller's workspace. |
| `sts-api-url` | Yes | | HTTPS base URL of the release token service, without a trailing slash. It is also the OIDC audience. |
| `merge-mode` | No | `review` | Set `admin-squash` only when the caller's release policy permits bypassing review. The token must be allowed to bypass the destination's rules. |

`changed` reports whether the prepared update differs from the versions `main` branch. When it is `true`, `pull-request-url` contains the created or reused PR URL. Each project and release uses a stable update branch, so reruns reuse its open PR. A rerun with the same proposed tree and base leaves the branch head intact. Updates use an explicit Git lease from the start of preparation and fail if another run changes the branch during the update.

The insertion script is fetched by commit SHA and checked against its expected SHA-256. The current versions checkout provides the data and base branch for the PR. The action runs the insertion script first and exchanges the job's OIDC token only when there is a change to publish. The installation token is used by the publishing step, and the token service action attempts to revoke it when the job finishes.
