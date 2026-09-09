# Release artifact utilities

Shared wheel transforms and signature verification for Astral's release binaries.
`setup-release-signing` outputs the scripts directory; pass it to packaging and
verification steps as `RELEASE_SIGNING_SCRIPTS`. Pin the action to a commit.

Install `uv` before invoking the Python scripts. They use PEP 723 metadata and
checked-in lockfiles; set `UV_LOCKED: 1` in release jobs. Native verification runs
on macOS or Windows. Use [`sign-macos`](../sign-macos/README.md) and
[`sign-windows`](../sign-windows/README.md) for the signing procedure.

```yaml
- id: setup-signing
  uses: astral-sh/github-actions/setup-release-signing@<commit>
- name: Extract wheel executables
  shell: bash
  env:
    RELEASE_SIGNING_SCRIPTS: ${{ steps.setup-signing.outputs.scripts }}
  run: uv run "$RELEASE_SIGNING_SCRIPTS/extract-wheel-binaries.py" --output unsigned dist/*.whl
```

## Scripts

| Script                                | Arguments                                                      | Purpose                                                                                                             |
| ------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `extract-wheel-binaries.py`           | `--output DIRECTORY WHEELS...`                                 | Extract `.data/scripts` members, preserving executable access.                                                      |
| `inject-signed-wheel-binaries.py`     | `--input WHEEL --output WHEEL --signed-binaries DIRECTORY`     | Replace every executable and regenerate `RECORD`.                                                                   |
| `verify-release-binaries-macos.py`    | `SIGNED PACKAGED BINARIES...`                                  | Require the exact executable inventory, byte equality, Apple trust, timestamp, and expected certificate.            |
| `verify-release-binaries-windows.ps1` | `-Signed DIRECTORY -BinaryDirectory DIRECTORY -Binaries NAMES` | Require the exact inventory, byte equality, trusted Authenticode signatures, and timestamps; run `signtool verify`. |

These scripts are for trusted Astral release artifacts that fit in memory.
Wheels must contain their executables directly in `.data/scripts`, as uv,
uv-build, and Ruff's wheels do. When extracting several wheels into one directory,
their executable names must be distinct. The replacement script requires a signed
file for every executable; other signed files may belong to a sibling wheel.
The caller checks the expected binary inventory after packaging.

The projects retain their target matrices, artifact downloads, GitHub archive
layouts, package assembly, and install/run smoke tests. After packaging, run the
native verifier to check that the expected executable inventory contains exactly
the signed bytes and that the operating system accepts their signatures. The
Windows verifier requires the Windows SDK's `signtool.exe` on the runner.
