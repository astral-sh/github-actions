# Select runners

Resolve logical runner roles from the shared [catalog](runners.json). The action
uses its bundled catalog and needs neither a checkout nor a GitHub token.

Each role contains an ordered list of candidates. Selection uses the first
candidate, or the first candidate marked `free` when `free-only` is enabled.
By default, workflows outside the `astral-sh` organization use only free
candidates. This uses the workflow repository owner: a contributor's pull request
to an Astral repository still runs on Astral's runners, while a workflow in the
contributor's fork uses GitHub-hosted alternatives. Astral repositories must have
access to the configured runner pools.

Pin the action to a full commit SHA so the resolver and catalog change together.
Runner selection is configuration, not a probe of runner capacity or provider
availability; an unavailable provider does not trigger another selection.

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

## Inputs and outputs

| Input       | Meaning                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------ |
| `free-only` | Optional `true` or `false` override. Defaults to `true` outside `astral-sh`.               |
| `required`  | Whitespace-separated roles that must resolve. Unknown or unavailable roles fail selection. |

| Output      | Meaning                                                            |
| ----------- | ------------------------------------------------------------------ |
| `runners`   | Compact JSON object mapping available roles to runner labels.      |
| `free-only` | `true` when only free candidates were eligible; otherwise `false`. |

Sizes in ordinary role names describe the preferred runner. Free fallbacks may
have fewer CPUs and less memory, so callers may need longer timeouts or less
parallelism. The `free` flag describes the public-repository runner tier, not a
billing guarantee for private repositories.

Specialized roles are omitted when no eligible candidate exists:

- `ubuntu-aarch64-pgo` requires the native 64 GB ARM runner used for release PGO.
  A caller may instead use `ubuntu-aarch64-4` with PGO disabled.
- `ubuntu-x86_64-codspeed` requires CodSpeed's walltime benchmark runner. Guard
  the benchmark job with an `if` checking that this role is present.

The `-github` variants retain the GitHub runner image where a workload uses it;
the corresponding ordinary Linux build roles use Depot's runner and cache.
The `-slim` role permits the constrained `ubuntu-slim` image as its free fallback.
