# Pull request review findings

Shared helpers for merging structured review findings and publishing one GitHub
review with inline comments. Review workflows own their prompts, output schemas,
repository setup, and completion criteria.

## Preparing findings

Check out `pull-request-review` at a pinned commit and install uv, then run
`bash pull-request-review/scripts/prepare.sh` in a separate job from the review.
Set `HEAD_SHA` to the reviewed commit and `REVIEW_RESULTS` to a JSON object mapping
review names to their GitHub job results. For example, a job that needs `security`
and `code-quality` can pass:

```yaml
env:
  REVIEW_RESULTS: >-
    {
      "Security": ${{ toJSON(needs.security) }},
      "Code quality": ${{ toJSON(needs.code-quality) }}
    }
```

Each successful job provides its review JSON in `outputs.result`. Skipped jobs
contribute no findings. Failed or cancelled jobs mark the combined review as
incomplete; findings from successful jobs can still be published. Malformed
output from a successful job fails preparation.

Reviews provide a `findings` array. Each finding has a `title`, `body`, `priority`,
and `code_location` with a repository-relative path, diff side, and line range.
Additional review-specific fields are ignored by the formatter. Each review
defines its own complete output schema. Identical findings are combined with all
their review names, and findings are ordered by priority. The script writes a
`result` step output containing a GitHub review payload and records review job
statuses in the job summary.

Use `!cancelled()` in the preparation job's condition so it can run when a review
job fails or is intentionally skipped. The publishing job also needs an explicit
status condition to publish partial results after a review failure.

## Publishing findings

Run `bash pull-request-review/scripts/publish.sh` in a separate publishing job
with these environment variables:

- `REVIEW_RESULT`: the prepared review payload.
- `HEAD_SHA`: the reviewed commit.
- `PULL_REQUEST_NUMBER`: the pull request to comment on.
- `GITHUB_REPOSITORY`: the target repository.
- `GH_TOKEN`: a token with `pull_requests: write` access to that repository.

The publisher skips empty findings, checks the current pull request head, and
submits all findings in one `COMMENT` review. The publishing job must check out
only the pinned helper implementation, not the reviewed repository. Keep token
acquisition and event authorization in the calling workflow so the token service
can authorize that workflow's identity.

The helpers use the standard GitHub Actions `RUNNER_TEMP`, `GITHUB_OUTPUT`, and
`GITHUB_STEP_SUMMARY` environment variables.
