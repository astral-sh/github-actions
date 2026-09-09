# Astral GitHub Actions

Shared GitHub Actions for Astral projects.

- [Prepare release signing inputs](prepare-release-signing/README.md): extract
  executables and check that wheels and GitHub archives agree.
- [macOS signing](sign-macos/README.md): Azure authentication, signing, and notarization.
- [Windows signing](sign-windows/README.md): Azure authentication, signing, and
  publisher and timestamp verification.
- [Assemble signed releases](assemble-signed-release/README.md): inject signed
  executables into wheels and GitHub archives, updating records and checksums.
- [Verify signed releases](verify-release/README.md): check packaged bytes and
  signatures on native runners.

The caller supplies [artifact declarations](release-artifacts/README.md), release
approval, runner selection, artifact transfers, and project-specific smoke tests.
Use the same pinned commit for all actions in a release.
