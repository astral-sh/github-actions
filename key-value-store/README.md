# Key-value store

Store workflow state with `key-value-store/put`, retrieve it with
`key-value-store/get`, and remove it with `key-value-store/delete`. Each action
requests a fresh GitHub Actions OIDC token and exchanges it for a short-lived
session with the configured service. No static secret or separate login step is
required.

The `scope` input requests a sharing boundary. The service authorizes
that scope and its operations against repository policy, then derives the namespace
from signed OIDC claims. Callers cannot supply another repository, PR, run, or job ID.
Use the same scope when writing, reading, and deleting a value.

## Usage

Configure `KEY_VALUE_SERVICE_URL` as a repository variable containing the HTTPS
origin of a compatible service, such as `https://kv.example.com`. Grant
`id-token: write` to each job that uses these actions. Pin all three actions to
the same full commit SHA.

The following `.github/workflows/ci.yml` example uses the default `job` scope.
The service's trusted policy must grant this workflow `read`, `write`,
and `delete` for `job`. The service reads its configured policy
path (default `.github/aghs-kv.json`) from the repository's `main`, independently
of the job's checkout. Protect that branch and policy edits.

```yaml
name: Workflow state
on: pull_request

permissions:
  id-token: write

jobs:
  state:
    runs-on: ubuntu-latest
    steps:
      - uses: astral-sh/github-actions/key-value-store/put@<commit-sha>
        with:
          service-url: ${{ vars.KEY_VALUE_SERVICE_URL }}
          scope: job
          key: build-sha
          value: ${{ github.sha }}

      - uses: astral-sh/github-actions/key-value-store/get@<commit-sha>
        id: stored
        with:
          service-url: ${{ vars.KEY_VALUE_SERVICE_URL }}
          scope: job
          key: build-sha

      - name: Compare the stored commit
        if: steps.stored.outputs.found == 'true'
        env:
          STORED_SHA: ${{ steps.stored.outputs.value }}
        run: test "$STORED_SHA" = "$GITHUB_SHA"

      - uses: astral-sh/github-actions/key-value-store/delete@<commit-sha>
        with:
          service-url: ${{ vars.KEY_VALUE_SERVICE_URL }}
          scope: job
          key: build-sha
```

The corresponding policy grants access to each PR job's own namespace:

```json
{
  "version": 1,
  "rules": [
    {
      "on": ["pull_request"],
      "caller_workflow": "ci.yml",
      "caller_ref": "refs/pull/*/merge",
      "permissions": {
        "job": ["read", "write", "delete"]
      }
    }
  ]
}
```

The actions run on Linux, macOS, and Windows with a runner that supports Node 24
actions. If the runner uses `HTTP_PROXY` or `HTTPS_PROXY`, set
`NODE_USE_ENV_PROXY: '1'` in the job environment.

## Inputs and outputs

All three actions accept these inputs:

| Input | Default | Description |
| --- | --- | --- |
| `service-url` | Required | HTTPS origin, without credentials, a path, a query, or a fragment. |
| `key` | Required | Case-sensitive key: 1–256 ASCII letters, digits, `.`, `_`, or `-`; cannot be `.` or `..`. |
| `audience` | The `service-url` origin | Audience requested from GitHub. Must match the service configuration; at most 2,048 UTF-8 bytes without whitespace. |
| `scope` | `job` | Requested sharing scope; the service must authorize it. See the scope table below. |

All scopes are confined to the authenticated owner and repository.

| Scope | Shared values |
| --- | --- |
| `pull-request` | The same PR and environment, across workflows and runs; requires a `pull_request` event |
| `workflow` | The same event, ref, environment, and caller workflow file, across runs |
| `run` | The same event, ref, environment, and workflow run, including retries |
| `run-attempt` | The same event, ref, environment, and one attempt of a workflow run |
| `job` | The same event, ref, environment, and one job execution |
| `repository` | Authorized callers across events, refs, and environments in the repository |

`run` requires a signed `run_id` claim. `run-attempt` additionally requires
`run_attempt`, and `job` additionally requires `check_run_id`. Missing required
claims fail the exchange.

Scopes have separate namespaces: `repository` access does not unlock values in
other scopes. Selecting `job` in an action does not revoke any broader grant
that the service policy gives that caller. Policy controls which scopes and
operations a job may request. All code within one job shares its job identity.

These actions require a service that supports scoped exchanges. Every exchange
sends the requested scope as JSON and requires the service to confirm it in the
response. A denied or unsupported scope fails, as does a
missing or mismatched confirmation. The actions never retry with another scope.

`put` also accepts:

| Input | Default | Description |
| --- | --- | --- |
| `value` | Empty | UTF-8 text to store, including its whitespace and newlines. |
| `path` | Empty | Regular file whose raw bytes are stored instead of `value`. Cannot be combined with a nonempty `value`. |

Values may contain up to 65,536 bytes. Omitting both `value` and `path` stores an
empty value. Writing an existing key replaces its value and resets its expiry.
Concurrent writes are last-write-wins; their order is not guaranteed. The service
sets the retention period. These actions do not choose a TTL.

`get` also accepts:

| Input | Default | Description |
| --- | --- | --- |
| `path` | Empty | New file for the raw bytes. The file must not already exist; parent directories are created as needed. |
| `mask-value` | `true` | Mask a retrieved text value in runner logs. Set `false` only for nonsensitive values. Does not apply to file downloads. |

`get` produces these outputs:

| Output | Description |
| --- | --- |
| `found` | `true` for an unexpired value, including an empty value; `false` for a missing or expired key. |
| `value` | UTF-8 text when `path` is omitted; otherwise empty. |
| `path` | Absolute path of the file created; empty when no file was written. |
| `expires-at` | Value expiry in Unix seconds; empty when the key was not found. |

A missing key succeeds with `found: 'false'`, empty remaining outputs, and no
file. Text mode rejects invalid UTF-8 and NUL bytes; use `path` for binary data.
GitHub may suppress masked values passed through job outputs, so use
`mask-value: 'false'` only when a nonsensitive value must cross that boundary.
Masking does not encrypt a value or prevent a later step from accessing it.

`put` and `delete` have no outputs. Deleting a missing key succeeds. Other service
errors fail the action. Requests have a 15-second timeout and are not retried;
after a network failure, a write may already have reached the service.

## Files

Use `path` to transfer raw bytes without putting the value in an action output:

```yaml
- uses: astral-sh/github-actions/key-value-store/put@<commit-sha>
  with:
    service-url: ${{ vars.KEY_VALUE_SERVICE_URL }}
    key: build-result
    path: ${{ runner.temp }}/build-result.bin

- uses: astral-sh/github-actions/key-value-store/get@<commit-sha>
  id: restored
  with:
    service-url: ${{ vars.KEY_VALUE_SERVICE_URL }}
    key: build-result
    path: ${{ runner.temp }}/restored-result.bin
```

Paths may be absolute or relative to the job's working directory. The input file
must already exist and cannot itself be a symlink. The output file is created
exclusively, with owner-only permissions where supported. Paths and their parent
directories must be trusted: parent symlinks are followed, and these actions do
not sandbox filesystem access. Prefer a fresh path under `runner.temp` for
downloads, outside directories controlled by pull request contents.

## Service API

| Request | Authentication | Successful response |
| --- | --- | --- |
| `POST /exchange`, JSON `{"scope":"job"}` | GitHub OIDC bearer token | JSON with `access_token`, `token_type: "Bearer"`, `expires_at` in Unix seconds, and a matching `scope`. |
| `PUT /kv/<key>`, raw bytes | Session bearer token | `204`. |
| `GET /kv/<key>` | Session bearer token | `200` with raw bytes and `X-Expires-At` in Unix seconds, or `404`. |
| `DELETE /kv/<key>` | Session bearer token | `204`, including for an absent key. |

Session tokens use the format `aghs_kv_` followed by 64 lowercase hexadecimal
characters. They remain internal to the action and are never action outputs.
Each invocation requests a new OIDC token because the service allows each OIDC
token to be exchanged once. No service deployment is included with these actions.

## Trust boundaries

The configured service receives the OIDC token and stored values. Keep
`service-url`, `audience`, and file paths in trusted workflow configuration;
do not derive them from pull request content. HTTPS certificate verification is
enabled by default, redirects are rejected, and response bodies are bounded.
OIDC and session tokens are masked before further requests, and error responses
are not printed.

Namespace isolation and operation permissions are enforced by the service using
policy from trusted `main`.
Jobs with grants to the same namespace can perform
their permitted operations on each other's values. Use `job` scope and suitable
policy grants to isolate job executions; this does not isolate steps within a
job. The service supports `pull_request`, `push`, `workflow_dispatch`, and
`schedule` contexts; it rejects `pull_request_target` and `workflow_run`.
Adding an environment changes the namespace except for `repository` scope.
Sessions are bearer credentials: anyone holding one can use its recorded
permissions until expiry. The service caches repository policy
for five minutes, so a removed grant may still authorize new sessions until the
cached policy expires. Existing sessions retain their permissions until expiry.

Treat retrieved values as untrusted data. Pass text through `env` and quote shell
variables, as above, or consume downloaded files as data. Do not interpolate a
retrieved `value` directly into a `run` script or execute downloaded contents.
