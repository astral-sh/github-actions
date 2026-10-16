# Verify signed release artifacts

Verify one target's assembled wheels and GitHub archive on a native runner. The
action installs `uv`. Windows also requires PowerShell 7 and the Windows SDK's
`signtool.exe`.

```yaml
- uses: astral-sh/github-actions/verify-release@<commit>
  with:
    target: ${{ toJSON(matrix.platform) }}
    signed-directory: signed/${{ matrix.platform.target }}
    wheels-directory: wheels/${{ matrix.platform.target }}
    github-archives-directory: github-archives
    macos-binary-identifiers: >-
      {"example":"sh.astral.example","example-helper":"sh.astral.example.helper"}
```

On macOS, `macos-binary-identifiers` must include exactly one stable signing
identifier for every binary name declared by the target's wheels. Verification
selects the corresponding subset for each packaged format.

`target` is one of the [declarations](../release-artifacts/README.md) used for
preparation. The action requires the declared wheel and archive inventories,
checks the archive checksum, and compares every packaged executable to the signing
job's output. It then runs the same native checks on both distribution formats:

- macOS: `codesign --verify --strict` with an Apple trust requirement, the
  configured signing identifier for each binary, a signing timestamp, and
  an embedded leaf certificate matching the signer's pinned certificate.
- Windows: a valid, timestamped Authenticode signature and `signtool verify /pa /all`.
  The signing action checked the publisher; byte equality binds these files to
  that output.

This checks packaging and signatures, not Gatekeeper's notarization lookup,
SmartScreen reputation, or installation behavior. Keep project-specific installer
and wheel smoke tests in the calling workflow.
