Write a replacement for the newest release section in `CHANGELOG.md`. It starts at the first
level-two heading and ends immediately before the next level-two heading.

Read the generated section, several preceding releases, and the local Git history. Inspect the
relevant changes when a generated title is ambiguous. Use local files and history as source material
without editing files or using the network.

- Keep the original release heading and date. Copy the `Contributors` section verbatim.
- Follow the section names and order defined by `[tool.rooster.section-labels]` in `pyproject.toml`.
  Keep explicitly categorized entries in their generated sections. Move an `Other changes` entry
  when it clearly fits another established section.
- Lead with the user-visible behavior. Preserve factual qualifiers, and preserve the impact and
  any supported migration guidance for breaking changes.
- Drop changes that clearly affect only CI, tests, or contributor tooling. Keep uncertain entries
  and maintenance changes that affect users or downstream integrations.
- Combine pull requests that implement one user-facing change. Split distinct changes when it
  improves clarity. Preserve each retained pull request's number and exact URL in the project's
  Markdown link format. Repeat the reference if its changes appear in more than one bullet.
- Keep each paragraph and list item on a single physical line. Use concise prose, put significant
  changes first within each section, and remove empty sections.

Return only the complete replacement release section, starting with the original level-two heading.
Apply the following project guidance.
