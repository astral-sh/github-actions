# Rust workspace cache

Cache Cargo dependencies and workspace artifacts with GitHub's cache service.
Cache keys use the compiler selected in the workspace, so unrelated toolchains
installed on the runner do not prevent sharing caches.

```yaml
- uses: astral-sh/github-actions/rust-workspace-cache@<commit-sha>
  with:
    profile: fast-build-nightly
    save-if: ${{ inputs.save-rust-cache == 'true' }}

- run: cargo test --locked --profile fast-build-nightly -Z checksum-freshness
  env:
    RUSTC_BOOTSTRAP: "1"
```

Install the selected Rust toolchain and Git before this action. The action uses
`rustc` and `cargo` in the configured `workspace`, respecting `rust-toolchain.toml`
and `RUSTUP_TOOLCHAIN`. Build with that same toolchain after restoring the cache.

The helpers prefer `uv` from `PATH`, requesting Python 3.11 or newer without
loading the caller's Python project or `uv` configuration. `uv` may download Python
if needed; the action does not install `uv`. Without `uv`, the helpers
looks for Python 3.11 or newer as `python3` on Linux and macOS, `python` on Windows,
or in the runner's Python tool cache. A failure from
`uv` fails the operation rather than retrying with Python. Keep Rust and the Python
runtime available until the job ends. A current `Cargo.lock` is required.

## Dependency-only caching

For smaller builds where restoring workspace artifacts costs more than rebuilding
them, disable workspace caching:

```yaml
- uses: astral-sh/github-actions/rust-workspace-cache@<commit-sha>
  with:
    cache-workspace-crates: "false"

- run: cargo build --locked
```

This retains compiled dependencies while removing workspace artifacts before
upload. It does not restore workspace input timestamps or require nightly Cargo.
The two modes use separate cache keys.

## Inputs

| Input                    | Default             | Description                                                            |
| ------------------------ | ------------------- | ---------------------------------------------------------------------- |
| `workspace`              | `.`                 | Cargo workspace directory, relative to the checkout or absolute.       |
| `target-directory`       | `target`            | Cargo target directory, relative to `workspace`.                       |
| `profile`                | `debug`             | Profile directories to prune in workspace mode, separated by newlines. |
| `prefix-key`             | `v1-rust-workspace` | Cache key prefix; change it to invalidate caches.                      |
| `key`                    | Empty               | Additional cache key.                                                  |
| `add-job-id-key`         | `true`              | Include the job ID; set to `false` to share caches between jobs.       |
| `cache-workspace-crates` | `true`              | Cache workspace artifacts as well as dependencies.                     |
| `cache-bin`              | `true`              | Cache binaries installed with Cargo after this action starts.          |
| `save-if`                | `true`              | Save a new cache after a successful job.                               |

The build must use the configured workspace and target directory. In workspace
mode, `profile` selects the directories to prune; dependency-only mode removes
workspace artifacts from every profile in the target directory.
Profiles can include a target triple, such as `x86_64-unknown-linux-gnu/debug`.
For jobs that build multiple profiles:

```yaml
- uses: astral-sh/github-actions/rust-workspace-cache@<commit-sha>
  with:
    profile: |
      debug
      profiling
```

An absolute `workspace` supports builds outside the checkout, including Windows
Dev Drives. Restore only one artifact cache per workspace; overlapping workspace
restores are rejected.

## Cache contents and keys

The action caches the target directory, Cargo's registry and Git dependencies,
and optionally Cargo-installed binaries. It removes incremental artifacts and
top-level build outputs before upload. Dependency sources remain cached
because build scripts can depend on their timestamps. Runner-provided binaries
are excluded, and restoring installed tools does not overwrite existing binaries.
`CARGO_INCREMENTAL` defaults to `0` when the caller has not set it.

Keys include the active compiler and Cargo versions, runner OS and architecture,
build environment, Cargo configuration, profiles, cache mode, manifests, and locked
registry and Git dependencies. Workspace package version changes do not invalidate
the dependency key. A changed dependency key can restore a compatible older entry;
changes to the compiler or keyed build configuration cannot. Set `key` to distinguish
build inputs not covered by these components.

`add-job-id-key: "false"` permits sharing when the remaining key components,
cached paths, and GitHub cache scope match. The `cache-hit` output is `true` only
for an exact match. Exact hits and `save-if: "false"` skip cleanup and upload.
The `native-v1` key namespace starts a new cache generation.

## Workspace artifact reuse

Use `-Z checksum-freshness` to reuse workspace artifacts across fresh checkouts.
When saving a new workspace cache, the action sets `CARGO_UNSTABLE_MTIME_ON_USE` to
`true` and removes superseded artifacts for workspace packages used by the build.
Other workspace artifacts and dependencies remain cached. Usage tracking requires
nightly Cargo or `RUSTC_BOOTSTRAP=1`; the action does not set `RUSTC_BOOTSTRAP`.
Each selected profile must contain active Cargo fingerprints when saving. Pruning
fails without them, preventing an upload without evidence of artifact usage.
Usage tracking is disabled for exact hits, read-only jobs, and dependency-only
caches.

Cargo's `checksum-freshness` does not replace every build-script timestamp check.
The action records hashes, modes, and timestamps for Git-tracked regular files in
workspace packages with build scripts, together with directory entry lists. After
restoring artifacts, it restores matching file timestamps and eligible directory
timestamps. Directories containing symlinks or entries outside the snapshot, and
their ancestors, retain their checkout timestamps. Changed tracked inputs or
directory entries within a current build-script package invalidate that package's
cached build-script runs and outputs in the selected profiles.

The action does not compare the contents of Git metadata, symlinks, untracked
files, or inputs outside these packages; Cargo's freshness rules still apply. Input metadata
is recorded alongside artifacts only when a new cache will be saved.

The action uses GitHub.com's `$/` references to load its helpers from the same
commit. GitHub Enterprise Server is not supported.
