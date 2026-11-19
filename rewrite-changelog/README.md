# Rewrite release changelog

Run this action after generating and committing the release files and before
pushing the branch for review. Codex reads the project checkout and returns a
replacement for its newest changelog section. The action checks the version and
date, applies the replacement, and commits any change as `Rewrite changelog`
using the caller's Git identity.

Use an Ubuntu runner with Bash, Git, and uv. Check out the caller repository with
full history at the workspace root. For ty, initialize the Ruff submodule and
commit its updated pointer along with the generated changelog. The action reads
the old and new pointers from the version bump commit.

```yaml
- uses: astral-sh/github-actions/rewrite-changelog@<commit-sha>
  with:
    project: ruff
    openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

Set `project` to `ruff` or `ty` to select the corresponding prompt.
The action uses read-only Codex permissions and uploads the session as a workflow
artifact. Keep the API key scoped to the trusted release preparation job.
