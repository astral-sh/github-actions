# PR security review

Review a pull request with Codex Security, check that every changed path was
reviewed, and prepare and publish inline findings.

The reusable workflow is
[`pull-request-security-review.yml`](../.github/workflows/pull-request-security-review.yml).
It loads its helpers from its own repository and commit, then checks out the
caller's repository to review the pull request.

## Usage

Pin the workflow to a full commit SHA. Restrict the caller to same-repository
pull requests: caller setup commands run before the Codex sandbox starts.

```yaml
jobs:
  security-review:
    if: github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository
    uses: astral-sh/github-actions/.github/workflows/pull-request-security-review.yml@<commit-sha>
    with:
      uv-version: "0.12.13"
      uv-checksum: "745765a3b6e360ad76743599ae5c42e9278c7edf8bbff9fc76d05bf2623a04dd"
    secrets: inherit
    permissions:
      contents: read
      issues: read
      pull-requests: read
      id-token: write
```

The caller needs an `automations` environment with `OPENAI_API_KEY` and
`STS_API_URL` secrets, and threat models in `agents/references/` by default.

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `uv-version` | Yes | | uv release used by setup and review helpers. |
| `uv-checksum` | Yes | | SHA-256 of the Linux x86-64 uv release archive. |
| `threat-models` | No | `agents/references` | Threat model directory in the caller's repository. |
| `setup-command` | No | Empty | Bash commands run at the caller workflow revision before switching to the PR head. |
| `runner` | No | `ubuntu-latest` | Linux x86-64 runner for the review. |
| `helper-runner` | No | `ubuntu-latest` | Runner for preparing and publishing findings. |

The `result` output contains the structured review. The `comments` output contains
the prepared GitHub comment payloads.

## Publishing integration

The publishing job obtains a `pull_requests: write` token from the caller's token
service. Astral's secure token service supports cross-repository reusable
workflows; the target repository's policy must authorize the caller and the exact
workflow identity, including the same commit SHA used by the caller:

```text
astral-sh/github-actions/.github/workflows/pull-request-security-review.yml@<commit-sha>
```
