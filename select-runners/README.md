# Select runners

Choose runners for CI jobs from the [runner inventory](runners.json), which
lists exact labels for Namespace, Depot, GitHub, and CodSpeed. The
[default roles](roles.json) map job requirements to ordered lists of those
labels. Both files ship with the action.

For each role, the action selects the first candidate. With `free-only`
enabled, it selects the first candidate in the `github-standard` group.
By default, workflows outside the `astral-sh` organization use only free
candidates. A pull request targeting an Astral repository runs on Astral's
runners. A workflow running in the contributor's fork uses GitHub-hosted
alternatives. Astral repositories must have
access to the configured runner pools.

Pin the action to a full commit SHA so the resolver, inventory, and roles
change together. Selection uses the configured labels and takes place before
GitHub schedules the dependent jobs. A queued job stays on its selected label.

## Usage

Run selection in an existing setup or planning job, then pass the `runners` JSON
output to dependent jobs or reusable workflows. The initial job needs a fixed
runner because its steps execute after GitHub schedules it.

```yaml
jobs:
  plan:
    runs-on: ubuntu-24.04
    outputs:
      runners: ${{ steps.runners.outputs.runners }}
      free-only: ${{ steps.runners.outputs.free-only }}
    steps:
      - uses: astral-sh/github-actions/select-runners@<commit-sha>
        id: runners
        with:
          required: ubuntu-x86_64-16 windows-x86_64-16

  test:
    needs: plan
    runs-on: ${{ fromJSON(needs.plan.outputs.runners).ubuntu-x86_64-16 }}
    steps:
      - run: echo "Run tests"
```

Reusable workflows can accept a single required `runners` string input and use
`${{ fromJSON(inputs.runners).ubuntu-x86_64-16 }}`. The caller remains responsible
for job permissions, conditions, timeouts, and workload settings.

To select other machines from the inventory, use `roles` to add a role or
replace the candidates for a default role. This example uses a 32-core
Namespace runner for Windows builds and a 32-core Depot runner for Linux
builds. Each role names a standard GitHub runner for forks.

```yaml
with:
  roles: |
    {
      "windows-build": ["namespace-profile-windows-2022-x86-64-32x64", "windows-2025"],
      "linux-build": ["depot-ubuntu-24.04-32", "ubuntu-24.04"]
    }
  required: windows-build linux-build
```

## Inputs and outputs

| Input       | Meaning                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------ |
| `free-only` | Optional `true` or `false` override. Defaults to `true` outside `astral-sh`.               |
| `roles`     | Optional JSON object mapping role names to ordered lists of inventory labels.              |
| `required`  | Whitespace-separated roles that must resolve. Unknown or unavailable roles fail selection. |

| Output      | Meaning                                                            |
| ----------- | ------------------------------------------------------------------ |
| `runners`   | Compact JSON object mapping available roles to runner labels.      |
| `free-only` | `true` when only free candidates were eligible; otherwise `false`. |

Sizes in ordinary role names describe the preferred runner. Free fallbacks may
have fewer CPUs and less memory, so callers may need longer timeouts or less
parallelism. GitHub provides the `github-standard` runners free of charge for
public repositories. Private repositories follow their GitHub billing plan.

Specialized roles are omitted when no eligible candidate exists:

- `ubuntu-aarch64-pgo` requires the native 64 GB ARM runner used for release PGO.
  A caller may instead use `ubuntu-aarch64-4` with PGO disabled.
- `ubuntu-x86_64-codspeed` requires CodSpeed's walltime benchmark runner. Guard
  the benchmark job with an `if` checking that this role is present.

The `-github` variants use the GitHub runner image. The corresponding Linux
build roles use Depot's runner and cache.
The `-slim` role permits the constrained `ubuntu-slim` image as its free fallback.
