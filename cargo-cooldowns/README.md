# Cargo dependency cooldowns

Run `astral-sh/github-actions/cargo-cooldowns` after checkout on an x86-64 Linux
runner. It checks every tracked `Cargo.lock` under `working-directory` (the
checkout root by default). To check a submodule, initialize it during checkout
and set `working-directory` to its path.

The default cooldown is seven days. To set a different cooldown or exempt crates,
pass a `policy` file relative to `working-directory`. An exclusion without a
`version` applies to all versions of that crate.

```toml
cooldown-days = 7
exclusions = [
  { name = "example", version = "1.2.3", reason = "Reviewed security fix." },
]
```

Give the job `contents: read` for checkout and `actions: read` to reuse crate
publication times from a successful push to the repository's default branch.
On a cache miss, the action queries the crates.io index.
