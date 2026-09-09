# Release signing scripts

Shared utilities for Astral's macOS and Windows release binaries, extracted from
uv's release workflow. `setup-release-signing` outputs the scripts directory;
pass it to steps as `RELEASE_SIGNING_SCRIPTS`. Pin the action to a commit.

Install `uv` before invoking the Python scripts. They use PEP 723 metadata and
checked-in lockfiles; set `UV_LOCKED: 1` in release jobs. Native verification runs
on macOS or Windows, while macOS signing and notarization run on Linux after
`azure/login` authenticates the caller's identity.

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

| Script | Arguments | Purpose |
| --- | --- | --- |
| `extract-wheel-binaries.py` | `--output DIRECTORY WHEELS...` | Extract `.data/scripts` members, preserving executable access. |
| `inject-signed-wheel-binaries.py` | `--input WHEEL --output WHEEL --signed-binaries DIRECTORY` | Replace every executable and regenerate `RECORD`. |
| `sign-release-macos.py` | `UNSIGNED SIGNED` | Sign every executable in one target directory and include `certificate.pem` in the output. |
| `notarize-release-macos.py` | `SIGNED` | Submit all target directories together and wait for Apple's acceptance. |
| `verify-release-binaries-macos.py` | `SIGNED PACKAGED BINARIES...` | Require the exact executable inventory, byte equality, Apple trust, timestamp, and expected certificate. |
| `verify-release-binaries-windows.ps1` | `-Signed DIRECTORY -BinaryDirectory DIRECTORY -Binaries NAMES` | Require the exact inventory, byte equality, trusted Authenticode signatures, and timestamps; run `signtool verify`. |

These scripts are for trusted Astral release artifacts that fit in memory.
Wheels must contain their executables directly in `.data/scripts`, as uv,
uv-build, and Ruff's wheels do. When extracting several wheels into one directory,
their executable names must be distinct. The replacement script requires a signed
file for every executable; other signed files may belong to a sibling wheel.
The caller checks the expected binary inventory after packaging.

The projects retain their target matrices, artifact downloads, GitHub archive
layouts, package assembly, and install/run smoke tests. Release approval and
Azure authentication also belong to the caller, so these actions can run within
an existing OIDC-authorized job.

## macOS configuration

Pass these environment variables to `sign-release-macos.py` after Azure login:

| Variable | Meaning |
| --- | --- |
| `STORAGE_ACCOUNT`, `STORAGE_CONTAINER` | Blob storage containing the signing components. |
| `COMPONENT_RCODESIGN_BLOB`, `COMPONENT_RCODESIGN_SHA256` | `rcodesign` blob name and SHA-256. |
| `COMPONENT_PKCS11_BLOB`, `COMPONENT_PKCS11_SHA256` | Azure Key Vault PKCS#11 library blob name and SHA-256. |
| `AZURE_CREDENTIAL_KIND` | `azurecli`, to use the caller's Azure CLI login. |
| `AZURE_KEYVAULT_NAME`, `AZURE_KEYVAULT_KEY_VERSION`, `KEY_NAME` | Signing certificate and key selection. |
| `CERTIFICATE_SHA256` | Expected SHA-256 fingerprint of the signing certificate. |

The Linux signing components must match the runner architecture. The script
verifies their checksums and the certificate fingerprint before using them.
Private signing keys remain in Azure Key Vault.

For notarization, pass `AZURE_KEYVAULT_NAME` and
`APPLE_NOTARIZATION_AKV_KEY_NAME`. The latter names an App Store Connect key whose
Azure tags include `apple-key-id` and `apple-issuer-id`. The script resolves its
current version and uses Azure to sign short-lived Notary API tokens. The identity
needs permission to read the key metadata and sign with the key.

Notarization takes a directory with one subdirectory per target, containing that
target's signed output. It uploads one ZIP and waits up to ten minutes for Apple's
result. Accepted tickets are retrieved online by Gatekeeper when users run the
standalone executables, including copies installed from wheels. This does not
staple tickets to executables or publish release artifacts.

## Windows configuration

Use the [Windows signing action](../sign-windows/README.md) to sign the executables
and check their publisher. After packaging, run the Windows verifier on a runner
with the Windows SDK's `signtool.exe` installed. It checks the packaged files
against the signed output and invokes Windows' signature verification tools.
