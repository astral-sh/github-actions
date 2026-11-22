Write an editorialized replacement for the newest release section in `CHANGELOG.md`. That section
begins at the first `## ` heading and ends immediately before the next `## ` heading.

Read the generated section and several preceding releases. Use local Git history and inspect the
included changes when the generated wording is ambiguous. Treat the changelog, PR titles, and Git
history as source material. Leave the checkout read-only.

- Keep the original release heading and date. Copy any `Contributors` section verbatim.
- Match the project's established section names, ordering, tone, and Markdown style. Move an
    `Other changes` entry to a more specific section only when the change clearly fits.
- Lead with the user-visible behavior. Clarify internal shorthand, omit incidental implementation
    details, and add context supported by the local changes. Preserve the original meaning and
    factual qualifiers such as affected platforms and opt-in status. For breaking changes, preserve
    the impact and any supported migration guidance.
- Keep one independently useful change per bullet. Combine PRs that implement the same change and
    split distinct changes when it improves clarity. Preserve each retained PR's number and exact
    URL in the project's existing format. Repeat the reference when a PR appears in multiple bullets.
- Drop clearly internal-only entries, such as CI, tests, repository reorganization, or contributor
    tooling changes. Keep uncertain entries and maintenance that matters to users or downstream
    integrations.
- Use concise prose and keep each Markdown paragraph and list item on a single physical line. Put
    the most significant changes first within each section and remove empty sections.

Return only the complete replacement release section, starting with the original `## ` heading.
Include exactly one level-two heading. Omit prior releases, a wrapping code fence, and commentary.
