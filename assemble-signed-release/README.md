# Assemble signed release artifacts

Replace every wheel and GitHub archive executable with the signing output,
regenerate wheel `RECORD` entries and archive checksums, and preserve other wheel
contents and archive metadata. Original artifacts are left untouched.

Install `uv` before calling the action. The output directory must not exist.

```yaml
- uses: astral-sh/github-actions/assemble-signed-release@<commit>
  with:
    targets: ${{ needs.prepare.outputs.artifacts }}
    prepared-directory: prepared
    signed-directory: signed
    output-directory: signed-artifacts
```

Use the same [target declarations](../release-artifacts/README.md) as preparation.
`prepared-directory` contains its `wheels/` and `github-archives/` directories.
`signed-directory` contains one directory per target, with exactly the declared
executables and, on macOS, the signing action's `certificate.pem`.

Assembly rechecks the original artifacts before replacing their executables.
It produces:

- `wheels/<system>/<target>/`: signed wheels grouped for native verification.
- `pypi/<package>/`: the same wheels grouped for publication.
- `github-archives/`: signed GitHub archives and their new checksum sidecars.

Assembly does not verify signatures. Run [`verify-release`](../verify-release/README.md)
on each target's native platform before publishing these outputs.
