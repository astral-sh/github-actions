# Pull request review findings

Shared helpers for formatting structured review findings and publishing inline
GitHub comments. Review workflows own their prompts, output schemas, repository
setup, and completion criteria.

## Preparing findings

Check out `pull-request-review` at a pinned commit and install uv, then run
`bash pull-request-review/scripts/prepare.sh` in a separate job from the review.
Set `REVIEW_RESULT` to the review JSON and `HEAD_SHA` to the reviewed commit.
The script writes a `result` step output containing GitHub comment payloads.

Reviews provide a `findings` array. Each finding has a `title`, `body`, `priority`,
and `code_location` with a repository-relative path, diff side, and line range.
Additional review-specific fields are ignored by the formatter. Each review
defines its own complete output schema.

## Publishing findings

Run `bash pull-request-review/scripts/publish.sh` in a separate publishing job
with these environment variables:

- `REVIEW_RESULT`: the prepared comment payloads.
- `HEAD_SHA`: the reviewed commit.
- `PULL_REQUEST_NUMBER`: the pull request to comment on.
- `GITHUB_REPOSITORY`: the target repository.
- `GH_TOKEN`: a token with `pull_requests: write` access to that repository.

The publisher skips empty findings and checks the current pull request head before
posting. The publishing job must check out only the pinned helper implementation,
not the reviewed repository. Keep token acquisition and event authorization in
the calling workflow so the token service can authorize that workflow's identity.

The helpers use the standard GitHub Actions `RUNNER_TEMP` and `GITHUB_OUTPUT`
environment variables.
