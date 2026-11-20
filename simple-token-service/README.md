# Simple token service

Exchange a GitHub Actions OIDC token for a short-lived GitHub App installation
token or an encrypted GitHub proxy capability. The token service policy authorizes the calling workflow, target
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

| Input           | Description                                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `exchange-url`  | Required HTTPS token exchange endpoint. Must be the `audience` URL followed by `/exchange`.                               |
| `audience`      | Required HTTPS OIDC audience configured in the service policy.                                                            |
| `repository`    | Target repository in `OWNER/REPO` form. Mutually exclusive with `repositories`.                                           |
| `repositories`  | Newline-delimited list of 2–10 distinct target repositories in `OWNER/REPO` form.                                         |
| `permissions`   | Newline-delimited GitHub App repository permissions, such as `contents: write`. Required when either target input is set. |
| `delivery`      | `token` (the default) or `github-proxy`.                                                                                  |
| `branch`        | Exact target branch for `github-proxy` delivery.                                                                          |
| `expected-head` | Expected previous branch head for `github-proxy` delivery, or forty zeroes for a new branch.                              |

Each target must authorize the requested permissions. For multiple repositories,
all targets must belong to the same GitHub App installation. Omit both target
inputs and `permissions` only when using a service policy that permits an empty
exchange request.

## Outputs

| Output          | Description                                                                  |
| --------------- | ---------------------------------------------------------------------------- |
| `token`         | Short-lived GitHub App installation token for `delivery: token`.             |
| `expires-at`    | Expiration time reported by GitHub.                                          |
| `repository`    | Repository authorized by a single-repository exchange.                       |
| `repositories`  | Newline-delimited repositories authorized by a multi-repository exchange.    |
| `ref`           | Git ref authorized by the service policy.                                    |
| `capability`    | Encrypted capability returned by `github-proxy` delivery instead of `token`. |
| `branch`        | Exact branch authorized by the capability.                                   |
| `expected-head` | Expected previous branch head authorized by the capability.                  |

For token delivery, the action masks the OIDC and installation tokens and attempts
to revoke an unexpired installation token when the job finishes, including after a failed step.
A failed revocation emits a warning. Keep the token within the job that requested
it.

When an HTTP proxy is configured, set `NODE_USE_ENV_PROXY: '1'` in the action's
environment so Node.js uses it for token requests and revocation.

## Branch-scoped proxy delivery

`delivery: github-proxy` requires a token service deployment with proxy delivery
enabled. It requests an encrypted capability for exactly one repository with
`contents: write`, an exact branch, and its expected previous head. The action
rejects `main` and `master` and is disabled when `RUNNER_DEBUG=1`.

Request the capability in a trusted setup job and pass it to a reusable workflow
through an explicitly declared secret:

```yaml
permissions: {}

jobs:
  setup:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    outputs:
      capability: ${{ steps.proxy.outputs.capability }}
    steps:
      - id: proxy
        uses: astral-sh/github-actions/simple-token-service@<commit-sha>
        with:
          exchange-url: ${{ secrets.STS_API_URL }}/exchange
          audience: ${{ secrets.STS_API_URL }}
          repository: example-org/example-repo
          permissions: |
            contents: write
          delivery: github-proxy
          branch: automation/fix-123
          expected-head: "0000000000000000000000000000000000000000"

  agent:
    needs: setup
    uses: ./.github/workflows/proxy-agent.yml
    permissions:
      contents: read
    secrets:
      proxy_capability: ${{ needs.setup.outputs.capability }}
```

The receiving workflow must declare `proxy_capability` under
`on.workflow_call.secrets` and pass `${{ secrets.proxy_capability }}` to
`astral-sh/github-actions/github-proxy`. This lets GitHub mask the capability
before logging action inputs. Do not pass it through ordinary inputs, environment
variables, shell interpolation, or `secrets: inherit`.

The issuing job leaves the capability output unmasked so GitHub can transfer it
between jobs. Treat it as a bearer credential: never print it or upload it as an
artifact. The receiving proxy action stores it in the checkout's `.git/config`;
never archive or upload `.git`. Use GitHub-hosted or isolated ephemeral runners.

Keep `id-token: write` out of the receiving job: an applicable service policy
could otherwise let it request a raw installation token. Derive the branch and
expected head from trusted metadata and
keep the setup job on a protected workflow. Use forty zeroes for a new branch or
its current object ID for an existing branch.

Proxy delivery returns `capability` instead of `token`. The proxy action attempts
to revoke the underlying installation token at the end of the receiving job; the
issuing job does not save it for installation-token revocation.
