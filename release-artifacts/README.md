# Release artifact declarations

The preparation, assembly, and verification actions share a target declaration.
The caller defines its wheel packages, executable names, and GitHub archive
layout once and passes the same declarations to each phase. Paths are relative to
the workspace unless absolute.

For example, a macOS target with one wheel package:

```json
{
  "target": "aarch64-apple-darwin",
  "system": "macos",
  "wheels": [
    {
      "package": "ruff",
      "directory": "wheel-artifacts/wheels_ruff-aarch64-apple-darwin",
      "binaries": ["ruff"]
    }
  ],
  "github-archive": "github-archives/ruff-aarch64-apple-darwin.tar.gz",
  "github-archive-members": ["ruff-aarch64-apple-darwin/ruff"]
}
```

Each wheel directory must contain exactly one matching `<package>-*.whl`. Its
`.data/scripts/` entries must exactly match `binaries`. Multiple wheel packages
may contribute executables to a target, but their executable names must be distinct.

GitHub archives must contain exactly the declared executable members. TAR archives
may also contain their parent directories. Supported formats are `.tar.gz` and
`.zip`, with an adjacent `.sha256` file in `sha256sum` format. Every archive
executable must have the same name and bytes as an executable in a wheel.

Use `system: windows` for Windows targets. Declare `.exe` names and the ZIP's
member paths, which may differ from the macOS TAR layout.

These scripts handle trusted, in-memory Astral release artifacts. They do not
build artifacts or discover which executables a project ought to ship. The caller
must declare every release target that needs signing; undeclared targets are not
processed. Preparation and assembly take an array of declarations, while native
verification takes one target at a time.
