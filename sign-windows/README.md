# Sign Windows executables

Authenticate with GitHub OIDC, copy all target directories, and sign their `.exe`
files using Azure Artifact Signing. Then require every output file to have a valid,
timestamped Authenticode signature from the configured publisher.

Run on Windows with Azure CLI installed, such as `windows-2025`. The caller's job
needs `id-token: write` and an environment authorized to use the configured Azure
identity. Release approval and artifact downloads/uploads belong to the caller.

```yaml
- uses: astral-sh/github-actions/sign-windows@<commit>
  with:
    unsigned-directory: ${{ github.workspace }}/unsigned
    signed-directory: ${{ github.workspace }}/signed
    azure-client-id: ${{ secrets.CODESIGN_AZURE_CLIENT_ID_WINDOWS }}
    azure-tenant-id: ${{ secrets.CODESIGN_AZURE_TENANT_ID_WINDOWS }}
    azure-subscription-id: ${{ secrets.CODESIGN_AZURE_SUBSCRIPTION_ID_WINDOWS }}
    endpoint: ${{ secrets.CODESIGN_ENDPOINT }}
    signing-account-name: ${{ secrets.CODESIGN_SIGNING_ACCOUNT_NAME }}
    certificate-profile-name: ${{ secrets.CODESIGN_CERTIFICATE_PROFILE_NAME }}
    certificate-subject: ${{ secrets.CODESIGN_CERTIFICATE_SUBJECT }}
```

Pin the action to a commit. Both directory paths are relative to the workspace
unless absolute. The input must contain one subdirectory per target, holding only
that target's executables. The output directory must not exist. It preserves the
target layout and leaves the unsigned inputs untouched.

The action uses SHA-256 for both file and timestamp digests and Microsoft's RFC
3161 timestamp service. Dependency caching is disabled for release signing.

After packaging, use `verify-release-binaries-windows.ps1` from
[`setup-release-signing`](../setup-release-signing/README.md) to compare the
packaged bytes to this action's output and verify their signatures again.
