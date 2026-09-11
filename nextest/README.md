# Sharded nextest

Use `.github/workflows/nextest.yml` to fan a numeric shard count out into
independent runner jobs. Every shard checks out the caller and invokes its
`.github/actions/nextest` composite action with `partition`, `partitions`, and
`save-cache` inputs. That repository-local action owns project-specific toolchain,
cache, feature, and test-fixture configuration.

```yaml
jobs:
  test-windows:
    uses: astral-sh/github-actions/.github/workflows/nextest.yml@<commit>
    with:
      name: cargo test on windows
      runs-on: windows-latest
      shards: 3
```

The workflow accepts 1–256 shards and disables matrix fail-fast so a failing
shard does not cancel the others. Its small planning job runs on `ubuntu-slim`.
The caller should gate the workflow as usual and grant only `contents: read`.
The checkout and repository-local action run with the caller's permissions.

The repository-local action can use `astral-sh/github-actions/nextest@<commit>`
after preparing its environment:

```yaml
- uses: astral-sh/github-actions/nextest@<commit>
  with:
    name: windows
    partition: ${{ inputs.partition }}
    partitions: ${{ inputs.partitions }}
    arguments: '["--workspace", "--profile", "ci"]'
```

The action installs nextest, passes the JSON argument array directly to Cargo,
and adds `--partition hash:N/T` when `T > 1`. One shard runs the unpartitioned
suite. It sets `INSTA_UPDATE=new` and `INSTA_PENDING_DIR`, uploads pending
snapshots after a failure, and uploads JUnit results even when tests fail.
Artifact names are `pending-snapshots-NAME[-N]` and `junit-results-NAME[-N]`;
the numeric suffix is omitted for one shard. Each independent suite in a
workflow run needs a distinct `name`.

`working-directory` selects the Cargo workspace. `junit-path` is relative to that
directory; `snapshots-path` is relative to the original checkout. Both accept
absolute paths. Artifacts default to 14-day retention. The nextest profile must
enable JUnit output if a JUnit artifact is required.

When moving jobs into this workflow, make any job-name-dependent build-cache
keys explicit. GitHub's aggregate reusable-workflow result includes every shard,
but individual check names acquire another reusable-workflow level.
