# Apply AI policy

`bot:ai-policy-comment` posts Astral's AI policy reminder on an issue or pull
request. `bot:ai-policy-close` also closes it; issues are closed as not planned.
Closed targets and removed labels are skipped. Each accepted invocation posts a
new comment, so rerunning after a partial failure can post the reminder again.

Run from a trusted workflow with a token scoped to the workflow repository:

```yaml
- uses: astral-sh/github-actions/ai-policy@<commit>
  with:
    token: ${{ steps.token.outputs.token }}
    number: ${{ inputs.issue || inputs.pull_request }}
    label: ${{ inputs.label }}
```

The token needs `issues: write` and `pull_requests: write`. Use the
[simple token service](../simple-token-service/) to obtain an installation token.
No checkout is needed.
