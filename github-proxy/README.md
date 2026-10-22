# GitHub proxy

Configure a Git remote to push through a GitHub proxy using an encrypted
capability for one repository, branch, and expected previous head. The action sets
a repository-scoped authorization header in the local Git configuration and
changes the remote's push URL.

Request the capability from a token service deployment that supports
`delivery: github-proxy`. Keep that exchange in a trusted setup job with
`id-token: write`, then pass the capability to a separate reusable workflow as an
explicitly declared secret. See the
[token service action](../simple-token-service/README.md#branch-scoped-proxy-delivery)
for the issuer inputs.

The receiving workflow can configure its remote as follows:

```yaml
on:
  workflow_call:
    secrets:
      proxy_capability:
        required: true

permissions:
  contents: read

jobs:
  agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<commit-sha>
        with:
          persist-credentials: false
      - uses: astral-sh/github-actions/github-proxy@<commit-sha>
        with:
          proxy-url: ${{ vars.PROXY_API_URL }}
          capability: ${{ secrets.proxy_capability }}
          repository: example-org/example-repo
      - run: git push origin HEAD:automation/fix-123
```

The push must match the repository, branch, and expected previous head authorized
by the capability. Keep `id-token: write` out of the receiving job: an applicable
service policy could otherwise let it request a raw installation token. Pass the
capability through the declared secret so GitHub masks it before logging action inputs; do not hand it off through
ordinary inputs, environment variables, shell interpolation, or `secrets: inherit`.

The issuing job leaves the capability output unmasked so GitHub can transfer it
between jobs. Treat it as a bearer credential: never print it or upload it as an
artifact. This action stores it in the checkout's `.git/config`; never archive or
upload `.git`. Use GitHub-hosted or isolated ephemeral runners.

Pin actions to full commit SHAs. Check out the repository before configuring the
proxy, and use `persist-credentials: false` so checkout does not install a separate
Git credential.

## Inputs

| Input        | Description                                                                        |
| ------------ | ---------------------------------------------------------------------------------- |
| `proxy-url`  | Required HTTPS origin of the deployed GitHub proxy.                                |
| `capability` | Required encrypted capability from the token service, passed as a declared secret. |
| `repository` | Required target repository in `OWNER/REPO` form.                                   |
| `remote`     | Git remote to configure. Defaults to `origin`.                                     |

## Outputs

| Output    | Description                                                        |
| --------- | ------------------------------------------------------------------ |
| `git-url` | HTTPS push URL for the configured repository, without credentials. |

The post action attempts to revoke the underlying installation token when the job
finishes, including after a failed step. A failed revocation logs a warning.
