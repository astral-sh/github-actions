# Sign Windows executables

Sign every `.exe` in a directory and its subdirectories using Azure Artifact
Signing. Then require every file to have a valid, timestamped Authenticode
signature from the configured publisher. The directory must contain only the
executables intended for distribution.

Run on Windows after `azure/login` authenticates the release identity. The
action uses that Azure CLI login. The caller owns OIDC permissions, release
approval, and artifact uploads.

Signing modifies the files in place. Copy the unsigned binaries to a separate
directory first if they are needed for packaging comparisons.

```yaml
- uses: astral-sh/github-actions/sign-windows@<commit>
  with:
    directory: ${{ github.workspace }}/signed
    endpoint: ${{ secrets.CODESIGN_ENDPOINT }}
    signing-account-name: ${{ secrets.CODESIGN_SIGNING_ACCOUNT_NAME }}
    certificate-profile-name: ${{ secrets.CODESIGN_CERTIFICATE_PROFILE_NAME }}
    certificate-subject: ${{ secrets.CODESIGN_CERTIFICATE_SUBJECT }}
```

The action uses SHA-256 for both file and timestamp digests and Microsoft's RFC
3161 timestamp service. Dependency caching is disabled for release signing.

After packaging, use `verify-release-binaries-windows.ps1` from
[`setup-release-signing`](../setup-release-signing/README.md) to compare the
packaged bytes to this action's output and verify their signatures again.
