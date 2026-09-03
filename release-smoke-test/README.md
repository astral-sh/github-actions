# Release smoke test

Run installation and smoke-test commands in a disposable Linux container, using
QEMU when testing another architecture. Completed release artifacts are mounted
read-only at `/dist`, so test dependencies and build backends cannot overwrite them.

Use a Linux runner with Docker and an image that provides `/bin/sh`. Pin both the
action revision and container image to immutable references.

```yaml
- name: Test wheel
  uses: astral-sh/github-actions/release-smoke-test@<commit-sha>
  env:
    PACKAGE_NAME: uv
    MODULE_NAME: uv
  with:
    image: python:3.11-bookworm@sha256:35d3a4a3d5e42e02ab916d44513a050689f12c0533d45598d229672503fe77ca
    artifacts: dist
    run: |
      pip install "${PACKAGE_NAME}" --no-index --find-links /dist --force-reinstall
      "${MODULE_NAME}" --help
      python -m "${MODULE_NAME}" --help
```

The calling workflow builds or downloads the artifacts before this step.

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `image` | Yes | | Container image for the test. |
| `platform` | No | `linux/amd64` | Docker platform, such as `linux/arm64` or `linux/arm/v7`. |
| `artifacts` | Yes | | Artifact directory relative to the caller's workspace, mounted at `/dist`. |
| `rust-toolchain` | No | | Rust toolchain file relative to the caller's workspace. Installs the selected toolchain before running the test. |
| `run` | Yes | | Commands run with `/bin/sh -euc` in `/test`. A failing command fails the action. |

`PACKAGE_NAME` and `MODULE_NAME` are forwarded from the caller's environment when
set. The container also receives `DEBIAN_FRONTEND=noninteractive`. Other runner
environment variables are not forwarded.

## Source distributions

Set `rust-toolchain` to install Rust from the package's toolchain file. The file is
mounted read-only at `/test/rust-toolchain.toml`; Rust installation and compilation
happen inside the container.

## Older Python images

The action provides `/pip-requirements.txt` with a hash-pinned pip wheel compatible
with Python 3.8 and newer. To use the provided pip version:

```sh
python -m pip install --upgrade --require-hashes -r /pip-requirements.txt
```
