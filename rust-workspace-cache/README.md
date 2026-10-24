# Rust workspace cache

Cache Cargo dependencies and workspace crates with `Swatinem/rust-cache`. Before
saving a new cache entry, remove superseded artifacts for workspace packages used
by the build. Pruning leaves dependencies and unused workspace packages untouched.

```yaml
- uses: astral-sh/github-actions/rust-workspace-cache@<commit-sha>
  with:
    key: ${{ hashFiles('Cargo.toml') }}
    profile: fast-build-nightly
    save-if: ${{ inputs.save-rust-cache == 'true' }}

- run: cargo test --locked --profile fast-build-nightly -Z checksum-freshness
  env:
    RUSTC_BOOTSTRAP: "1"
```

Install Rust and Git before this action. Timestamp restoration and pruning use
`uv` from `PATH` when available, requesting Python 3.11 or newer without discovering
the caller's Python project or `uv` configuration files. `uv` may download Python
if no compatible interpreter is available. The action does not install `uv`.

If `uv` is not found, Python 3.11 or newer must be available as `python3` on
Linux and macOS, or `python` on Windows. Restoring an input snapshot and saving or
pruning a cache require `cargo` and a current `Cargo.lock`. Keep Rust and the Python
runtime available until the job ends. A failure from `uv` fails the operation; it
does not retry with Python.

The action sets `CARGO_UNSTABLE_MTIME_ON_USE` to `true` for subsequent steps when
`save-if` is `true` and no exact cache match was restored; otherwise it sets the
variable to `false`. Usage tracking requires nightly Cargo or `RUSTC_BOOTSTRAP=1`.
Use `-Z checksum-freshness` to reuse workspace artifacts across fresh checkouts.
The action does not set `RUSTC_BOOTSTRAP` or choose a Rust toolchain.

Pruning runs after a successful job, before `Swatinem/rust-cache` saves the cache.
Exact cache hits and `save-if: "false"` skip pruning. Pruning fails if no active
Cargo fingerprints are found, preventing a new cache from being saved without
evidence that Cargo tracked artifact usage.

## Inputs

| Input              | Default             | Description                                                                                                                              |
| ------------------ | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `workspace`        | `.`                 | Cargo workspace directory, relative to the checkout or absolute.                                                                         |
| `target-directory` | `target`            | Cargo target directory, relative to `workspace`.                                                                                         |
| `profile`          | `debug`             | Profile directories within `target-directory`, separated by newlines, such as `debug`, `profiling`, or `x86_64-unknown-linux-gnu/debug`. |
| `prefix-key`       | `v1-rust-workspace` | Cache key prefix.                                                                                                                        |
| `key`              | Empty               | Additional cache key.                                                                                                                    |
| `add-job-id-key`   | `true`              | Include the job ID in the cache key; set to `false` to share entries across jobs.                                                        |
| `cache-bin`        | `true`              | Cache binaries installed with Cargo.                                                                                                     |
| `save-if`          | `true`              | Whether to save a new cache entry after a successful job.                                                                                |

`workspace` and `target-directory` configure the cached paths. The build command
must use the same workspace and target directory. `profile` selects the directories
to prune; other profile directories are left unchanged. When pruning runs, each
selected profile must contain active Cargo fingerprints from the job.

For jobs that build multiple profiles:

```yaml
- uses: astral-sh/github-actions/rust-workspace-cache@<commit-sha>
  with:
    profile: |
      debug
      profiling
```

With `add-job-id-key: "false"`, jobs can share entries when the remaining cache key
components and GitHub cache scope also match.

The `cache-hit` output reports whether an exact cache match was restored.

## Build-script input timestamps

Cargo's `checksum-freshness` does not replace every build-script timestamp check.
Fresh checkout timestamps can therefore invalidate cached workspace builds even
when their source files are unchanged. The action caches hashes, modes, and
timestamps for Git-tracked regular files in workspace packages with build scripts,
together with their directory entry lists. After restoring artifacts, it restores
timestamps for matching files and for directories whose entry lists match and
whose contents consist only of tracked regular files in the snapshot and
directories containing them. It leaves the timestamps of directories containing
symlinks or entries outside the snapshot, and their ancestors, unchanged. Changes to
tracked inputs or directory entries within a current build-script package
invalidate that package's cached runs and their output directories in the selected
profiles.

The action does not compare the contents of Git metadata, symlinks, untracked
files, or inputs outside these packages; Cargo's usual freshness rules still apply.
Enable `checksum-freshness` for Rust source reuse across fresh checkouts. Restore
one artifact cache per workspace; overlapping workspace restores are rejected.

The action adds `-build-inputs-v1` to `prefix-key` and caches the input metadata
alongside the Cargo artifacts. The cache entry is populated when saving is enabled
and the job succeeds. Metadata is recorded only when a new artifact cache will be
saved; exact hits and read-only jobs restore the snapshot when available.

## Windows workspaces

An absolute `workspace` supports builds outside the checkout, including a Dev Drive:

```yaml
- uses: astral-sh/github-actions/rust-workspace-cache@<commit-sha>
  with:
    workspace: ${{ env.UV_WORKSPACE }}
    profile: fast-build-nightly
    key: ${{ hashFiles('Cargo.toml') }}
    add-job-id-key: "false"
    save-if: ${{ inputs.save-rust-cache == 'true' }}
```

The action uses GitHub.com's `$/` reference to load its pruning helper from the
same commit. GitHub Enterprise Server is not supported.
