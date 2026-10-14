# PR security review

Review a pull request with Codex Security, check that every changed path was
reviewed, and prepare and publish inline findings.

The reusable workflow is
[`pull-request-security-review.yml`](../.github/workflows/pull-request-security-review.yml).
It loads its helpers from its own repository and commit, then checks out the
caller's repository to review the pull request. The workflow requires GitHub.com
and Actions runner 2.336.0 or newer for the
[`$/` action reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#example-using-an-action-in-the-same-repository-as-the-workflow-at-the-running-commit-recommended),
which loads the action from the workflow's own commit outside the caller checkout.

The prompt, schema, plugin setup, and path coverage checks live here. Formatting
and publishing findings use the shared [pull request review helpers](../pull-request-review/).

The [composite action](action.yml) runs only the security review and returns its
structured `result` after the path coverage check succeeds. Use it when a caller
combines security findings with other reviews before publishing. The caller owns
the job's Linux x86-64 runner, environment, timeout, and read-only GitHub permissions. Pass `openai-api-key`, `github-token`,
`pull-request-number`, `base-sha`, `head-sha`, `uv-version`, and `uv-checksum`.
The action also accepts the `threat-models` and `setup-command` inputs described
below. It checks out the caller repository and saves its configuration before
switching to the requested pull request head. Run other reviewers in separate
jobs: this action replaces the checkout and removes sudo access.

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
the prepared GitHub review payload.

## Combining reviewers

Use the composite action in a reviewer job and pass its job output to the
[shared preparation and publishing helpers](../pull-request-review/). The action
does not publish findings itself.

```yaml
jobs:
  security:
    if: github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    environment: automations
    timeout-minutes: 30
    permissions:
      contents: read
      issues: read
      pull-requests: read
    outputs:
      result: ${{ steps.review.outputs.result }}
    steps:
      - id: review
        uses: astral-sh/github-actions/security-pr-review@<commit-sha>
        with:
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
          pull-request-number: ${{ github.event.pull_request.number }}
          base-sha: ${{ github.event.pull_request.base.sha }}
          head-sha: ${{ github.event.pull_request.head.sha }}
          uv-version: "0.12.13"
          uv-checksum: "745765a3b6e360ad76743599ae5c42e9278c7edf8bbff9fc76d05bf2623a04dd"
```

## Publishing integration

The publishing job obtains a `pull_requests: write` token from the caller's token
service. Astral's secure token service supports cross-repository reusable
workflows; the target repository's policy must authorize the caller and the exact
workflow identity, including the same commit SHA used by the caller:

```text
astral-sh/github-actions/.github/workflows/pull-request-security-review.yml@<commit-sha>
```
