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

Install Rust before this action. Python 3.11 or newer must be available as
`python3` on Linux and macOS, or `python` on Windows, when the job ends. Pruning
also requires `cargo` and a current `Cargo.lock` in the workspace at that point.

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

| Input              | Default             | Description                                                                                                    |
| ------------------ | ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `workspace`        | `.`                 | Cargo workspace directory, relative to the checkout or absolute.                                               |
| `target-directory` | `target`            | Cargo target directory, relative to `workspace`.                                                               |
| `profile`          | `debug`             | Profile directory within `target-directory`, such as `fast-build-nightly` or `x86_64-unknown-linux-gnu/debug`. |
| `prefix-key`       | `v1-rust-workspace` | Cache key prefix.                                                                                              |
| `key`              | Empty               | Additional cache key.                                                                                          |
| `add-job-id-key`   | `true`              | Include the job ID in the cache key; set to `false` to share entries across jobs.                              |
| `cache-bin`        | `true`              | Cache binaries installed with Cargo.                                                                          |
| `save-if`          | `true`              | Whether to save a new cache entry after a successful job.                                                      |

`workspace` and `target-directory` configure the cached paths. The build command
must use the same workspace and target directory. `profile` selects the directory
to prune; other profile directories are left unchanged.

With `add-job-id-key: "false"`, jobs can share entries when the remaining cache key
components and GitHub cache scope also match.

The `cache-hit` output reports whether an exact cache match was restored.

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
