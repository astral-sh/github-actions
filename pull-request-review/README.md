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

Each reviewer must run in a separate job and expose its review JSON as the
`result` job output. Each successful job must provide valid JSON, including an
empty `findings` array when it has no findings. Missing or malformed output from a
successful job fails preparation. Skipped jobs contribute no findings. Failed or cancelled jobs mark the combined review as
incomplete; their outputs are ignored, and findings from successful jobs can
still be published.

Reviews provide a `findings` array. Each finding has a `title`, `body`, `priority`,
and `code_location` with a repository-relative path, diff side, and line range.
Additional review-specific fields are ignored by the formatter. Each review
defines its own complete output schema. Findings with identical formatted text,
priority, path, diff side, and line range are combined with all their review names.
Different wording or priorities remain separate. Findings are ordered by priority.
The script writes a `result` step output containing a GitHub review payload and records review job
statuses in the job summary.

The preparation job must list every reviewer in `needs` and use
`if: ${{ !cancelled() }}` so it runs after a review fails or is intentionally
skipped. To publish partial results, the publishing job must also override the
implicit success condition while requiring successful preparation:

```yaml
needs: prepare
if: ${{ !cancelled() && needs.prepare.result == 'success' && needs.prepare.outputs.result != '' && fromJSON(needs.prepare.outputs.result).comments[0] != null }}
```

Cancellation of the workflow prevents both jobs from starting. If no successful
review has findings, preparation records the statuses in the job summary and
publishing is skipped.

For a single reviewer, `REVIEW_RESULT` still accepts the raw review JSON. It is
treated as one successful review named `Review`. Set only one of `REVIEW_RESULT`
or `REVIEW_RESULTS`. Both input forms produce the same combined review payload;
use the same helper commit for preparation and publishing.

## Publishing findings

Run `bash pull-request-review/scripts/publish.sh` in a separate publishing job
with these environment variables:

- `REVIEW_RESULT`: the prepared review payload.
- `HEAD_SHA`: the reviewed commit.
- `PULL_REQUEST_NUMBER`: the pull request to comment on.
- `GITHUB_REPOSITORY`: the target repository.
- `GH_TOKEN`: a token with `pull_requests: write` access to that repository.

The publisher requires the payload's `commit_id` to match `HEAD_SHA`, skips empty
findings, checks the current pull request head, and submits all findings in one
`COMMENT` review tied to the reviewed commit. The head check and review submission
are separate API requests; a push between them can still make the review outdated.
The publishing job must check out only the pinned helper implementation, not the
reviewed repository. Keep token
acquisition and event authorization in the calling workflow so the token service
can authorize that workflow's identity.

The helpers use the standard GitHub Actions `RUNNER_TEMP`, `GITHUB_OUTPUT`, and
`GITHUB_STEP_SUMMARY` environment variables.
