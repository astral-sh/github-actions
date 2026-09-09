# Prepare release signing inputs

Extract executables from the declared wheels, check each GitHub archive's checksum
and inventory, and require its executable bytes to match the wheels. Preserve the
original artifacts for assembly after signing.

Install `uv` before calling the action. The output directory must not exist.

```yaml
- uses: astral-sh/github-actions/prepare-release-signing@<commit>
  with:
    targets: ${{ steps.plan.outputs.artifacts }}
    output-directory: prepared
```

`targets` is a JSON array of [target declarations](../release-artifacts/README.md).
The output contains:

- `unsigned/<system>/<target>/`: executables to sign. Pass each system directory
  to its signing action, preserving the target subdirectories during transfer.
- `wheels/<target>/`: original wheels for assembly.
- `github-archives/`: original GitHub archives and checksum sidecars for assembly.

Transfer `wheels/` and `github-archives/` together, preserving these paths, for
[`assemble-signed-release`](../assemble-signed-release/README.md).
