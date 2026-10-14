# Astral GitHub Actions

Shared GitHub Actions for Astral projects.

- [Create release pull request](create-release-pr/): commit prepared release files
  and create or update a pull request.
- [Release smoke test](release-smoke-test/): test release artifacts in disposable containers.
- [PR security review](security-pr-review/): review pull requests with Codex Security.
- [PR review findings](pull-request-review/): format and publish structured review findings.
- [Plan release signing](plan-release-signing/README.md): derive native
  verification matrices and artifact declarations from cargo-dist targets.
- [Prepare release signing inputs](prepare-release-signing/README.md): extract
  executables and check that wheels and GitHub archives agree.
- [macOS signing](sign-macos/README.md): Azure authentication, signing, and notarization.
- [Windows signing](sign-windows/README.md): Azure authentication, signing, and
  publisher and timestamp verification.
- [Assemble signed releases](assemble-signed-release/README.md): inject signed
  executables into wheels and GitHub archives, updating records and checksums.
- [Verify signed releases](verify-release/README.md): check packaged bytes and
  signatures on native runners.
- [Verify packaged binaries](verify-binaries/README.md): use the same native
  checks with a project's own archive adapter.

The caller supplies package executable inventories, release approval, artifact
transfers, and project-specific smoke tests. Use the same pinned commit for all
actions in a release.

## Releases

This repository uses CalVer tags: `YYYY.MM.DD.0` for the first release on a date,
then `YYYY.MM.DD.1`, `YYYY.MM.DD.2`, etc. There is no `v` prefix. Use the
same tag's full commit SHA for every action in a caller's release workflow.

To release:

1. Run **Prepare release** on the default branch. Leave `version` blank to use
   today's UTC date and the next available generation, or enter `YYYY.MM.DD.N`.
   It opens or updates `release/<version>` using `create-release-pr`.
2. Review and merge that PR.
3. Run **Release** on the default branch. Leave `version` blank to release
   the prepared version, or enter it explicitly as a check. The workflow
   refuses an existing tag, tags its exact commit, and creates a GitHub release
   with generated notes.
