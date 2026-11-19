# Rewrite release changelog

Run this action after generating and committing the release files and before
pushing the branch for review. Codex reads the project checkout and returns a
replacement for its newest changelog section. The action checks the version and
date, applies the replacement, and commits any change as `Rewrite changelog`
using the caller's Git identity.

Use an Ubuntu runner with Bash, Git, and uv. Check out the caller repository with
full history at the workspace root, including any submodules that the prompt
needs to inspect.

```yaml
- uses: astral-sh/github-actions/rewrite-changelog@<commit-sha>
  with:
    prompt-file: agents/prompts/editorialize-changelog.md
    openai-api-key: ${{ secrets.OPENAI_API_KEY }}
```

Keep the editorial prompt in the caller repository and pass its path relative
to the workspace root. The action prefixes the prompt with the release version
from `uv version --short`. Ask Codex for the complete replacement release
section, starting with the original level-two heading and release date.

The optional `model`, `effort`, and `codex-version` inputs default to
`gpt-6.2-sol`, `high`, and `0.170.0`. Choose an effort supported by the model
and a CLI version compatible with the pinned Codex Action. The `codex-version`
input selects the version of both the CLI and the Responses API proxy.

The action uses read-only Codex permissions and uploads the session as a workflow
artifact. Keep the API key scoped to the trusted release preparation job.
