# Verify packaged native binaries

Use this action when a project's archive format is not covered by
[`verify-release`](../verify-release/README.md). The project must extract every
native executable and library from its assembled archive, preserving the paths
used for signing. This action compares those bytes with the signing output and
runs the same macOS or Windows trust checks as `verify-release`.

Install `uv` first and use a native runner. Windows also requires PowerShell 7
and the Windows SDK's `signtool.exe`.

```yaml
- uses: astral-sh/github-actions/verify-binaries@<commit>
  with:
    signed-directory: signed/aarch64-apple-darwin
    binaries-directory: packaged-binaries
```

The caller remains responsible for the archive's complete native-code inventory,
metadata, checksums, and installation smoke tests.
