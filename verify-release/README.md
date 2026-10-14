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
```

`target` is one of the [declarations](../release-artifacts/README.md) used for
preparation. The action requires the declared wheel and archive inventories,
checks the archive checksum, and compares every packaged executable to the signing
job's output. It then runs the same native checks on both distribution formats:

- macOS: `codesign --verify --strict` with an Apple trust requirement, a signing
  timestamp, and an embedded leaf certificate matching the signer's pinned certificate.
- Windows: a valid, timestamped Authenticode signature and `signtool verify /pa /all`.
  The signing action checked the publisher; byte equality binds these files to
  that output.

This checks packaging and signatures, not Gatekeeper's notarization lookup,
SmartScreen reputation, or installation behavior. Keep project-specific installer
and wheel smoke tests in the calling workflow.

To require debug companions and embedded cargo-auditable SBOMs to remain valid after
signing, also provide the original executables and select the wheel packages that
ship this metadata:

```yaml
unsigned-directory: unsigned/${{ matrix.platform.target }}
metadata-packages: '["uv"]'
```

This requires Rust installed through rustup; the action installs
`llvm-tools-preview`. macOS also requires Xcode's `dwarfdump`. For every executable
in the selected packages, verification requires a matching Mach-O UUID (per
architecture) or PE CodeView PDB GUID and age, and identical, valid compressed
JSON in the `.dep-v0` section. This check requires a single SBOM section per
executable; universal Mach-O files with multiple SBOM sections are unsupported.
Missing metadata fails verification. Other declared
packages still receive the usual packaging and signature checks.

Run the metadata verification tests with:

```sh
python -m unittest discover -s release-artifacts -p test_verify.py
```
