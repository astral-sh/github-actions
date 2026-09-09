# Sign and notarize macOS executables

Sign every executable in each target directory through Azure Key Vault, then
submit all targets to Apple together and wait for notarization to be accepted.
The action installs a pinned version of `uv`, authenticates with GitHub OIDC,
and runs its PEP 723 scripts with their checked-in lockfiles.

Run on Linux x86_64 with Azure CLI installed, such as `ubuntu-24.04`. The caller's
job needs `id-token: write` and an environment authorized to use the configured
Azure identity. Release approval and artifact downloads/uploads belong to the
caller.

```yaml
- uses: astral-sh/github-actions/sign-macos@<commit>
  with:
    unsigned-directory: ${{ github.workspace }}/unsigned
    signed-directory: ${{ github.workspace }}/signed
    azure-client-id: ${{ secrets.CODESIGN_AZURE_CLIENT_ID_MACOS }}
    azure-tenant-id: ${{ secrets.CODESIGN_AZURE_TENANT_ID_MACOS }}
    azure-subscription-id: ${{ secrets.CODESIGN_AZURE_SUBSCRIPTION_ID_MACOS }}
    storage-account: ${{ secrets.CODESIGN_STORAGE_ACCOUNT }}
    storage-container: ${{ secrets.CODESIGN_STORAGE_CONTAINER }}
    component-rcodesign-blob: ${{ secrets.CODESIGN_COMPONENT_RCODESIGN_BLOB }}
    component-rcodesign-sha256: ${{ secrets.CODESIGN_COMPONENT_RCODESIGN_SHA256 }}
    component-pkcs11-blob: ${{ secrets.CODESIGN_COMPONENT_PKCS11_BLOB }}
    component-pkcs11-sha256: ${{ secrets.CODESIGN_COMPONENT_PKCS11_SHA256 }}
    azure-keyvault-name: ${{ secrets.CODESIGN_AZURE_KEYVAULT_NAME }}
    azure-keyvault-key-version: ${{ secrets.CODESIGN_AZURE_KEYVAULT_KEY_VERSION }}
    key-name: ${{ secrets.CODESIGN_KEY_NAME }}
    certificate-sha256: ${{ secrets.CODESIGN_CERTIFICATE_SHA256 }}
    apple-notarization-akv-key-name: ${{ secrets.CODESIGN_APPLE_NOTARIZATION_AKV_KEY_NAME }}
```

Pin the action to a commit. Both directory paths are relative to the workspace
unless absolute. The input must contain one subdirectory per target, holding only
that target's executables. The output directory must not exist. It preserves the
target layout and includes `certificate.pem` in every target directory for later
verification. The unsigned inputs are preserved.

The action downloads `rcodesign`, the Azure Key Vault PKCS#11 library, and the
signing certificate once for all targets. It verifies the component SHA-256
digests and certificate fingerprint before signing with the hardened runtime.
Private signing keys remain in Azure Key Vault.

The notarization key is an App Store Connect key in the same vault, with Azure
tags `apple-key-id` and `apple-issuer-id`. The action resolves its current version
and asks Azure to sign short-lived Notary API tokens. The identity needs permission
to read the key metadata and sign with the key.

Notarization uploads one ZIP and waits up to ten minutes for Apple's result.
Accepted tickets are retrieved online by Gatekeeper when users run the standalone
executables, including copies installed from wheels. Tickets cannot be stapled
to these executables.

Use [`assemble-signed-release`](../assemble-signed-release/README.md) to package
the output, then [`verify-release`](../verify-release/README.md) on macOS to check
the packaged bytes, signatures, and certificate.
