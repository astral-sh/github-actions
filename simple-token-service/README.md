# Simple token service

Exchange a GitHub Actions OIDC token for a short-lived GitHub App installation
token. The token service policy authorizes the calling workflow, target
repositories, and requested permissions.

```yaml
permissions: {}

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - name: Get release token
        id: token
        uses: astral-sh/github-actions/simple-token-service@<commit-sha>
        with:
          exchange-url: ${{ secrets.STS_API_URL }}/exchange
          audience: ${{ secrets.STS_API_URL }}
          repository: ${{ github.repository }}
          permissions: |
            contents: write
      - name: Use release token
        env:
          GH_TOKEN: ${{ steps.token.outputs.token }}
          GH_REPO: ${{ github.repository }}
        run: gh release list
```

Pin the action to a full commit SHA. The job needs `id-token: write` to request an
OIDC token; the service policy and GitHub App installation determine which
repository permissions it can receive.

## Inputs

| Input          | Description                                                                                                               |
| -------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `exchange-url` | Required HTTPS token exchange endpoint. Must be the `audience` URL followed by `/exchange`.                               |
| `audience`     | Required HTTPS OIDC audience configured in the service policy.                                                            |
| `repository`   | Target repository in `OWNER/REPO` form. Mutually exclusive with `repositories`.                                           |
| `repositories` | Newline-delimited list of 2–10 distinct target repositories in `OWNER/REPO` form.                                         |
| `permissions`  | Newline-delimited GitHub App repository permissions, such as `contents: write`. Required when either target input is set. |

Each target must authorize the requested permissions. For multiple repositories,
all targets must belong to the same GitHub App installation. Omit both target
inputs and `permissions` only when using a service policy that permits an empty
exchange request.

## Outputs

| Output         | Description                                                               |
| -------------- | ------------------------------------------------------------------------- |
| `token`        | Short-lived GitHub App installation token.                                |
| `expires-at`   | Expiration time reported by GitHub.                                       |
| `repository`   | Repository authorized by a single-repository exchange.                    |
| `repositories` | Newline-delimited repositories authorized by a multi-repository exchange. |
| `ref`          | Git ref authorized by the service policy.                                 |

The action masks the OIDC and installation tokens and attempts to revoke an
unexpired installation token when the job finishes, including after a failed step.
A failed revocation emits a warning. Keep the token within the job that requested
it.

When an HTTP proxy is configured, set `NODE_USE_ENV_PROXY: '1'` in the action's
environment so Node.js uses it for token requests and revocation.
