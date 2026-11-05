# Docker build and publication

These actions implement Astral's Docker release conventions for uv, Ruff, and ty.
They interpret the `cargo-dist` plan, check release versions against
`pyproject.toml`, generate standard tags and OCI metadata, and build multi-platform
images with Depot. Release candidates are saved and published later without
rebuilding.

The calling repository supplies its Depot project IDs, binary names, Dockerfile,
and image inventory. It owns registry credentials, job permissions, protected
environments, and release approval.

Use Linux runners with Docker, Bash, Python 3.11 or newer, and `jq`. Grant build jobs
`contents: read` and `id-token: write`, and configure the selected Depot project's
[GitHub Actions OIDC trust](https://depot.dev/docs/container-builds/integrations/github-actions).
Production and development builds should use separate Depot projects. Pin each
action reference to the same reviewed commit.

## Plan the build

`docker-plan` selects the build mode, Depot project, registry destinations, and
variant matrix. It expects `astral-sh/<name>` or `astral-sh/<name>-dev` as the
calling repository.

```yaml
- uses: astral-sh/github-actions/docker-plan@<commit-sha>
  id: plan
  with:
    name: ruff
    plan: ${{ inputs.plan }}
    push-dev: ${{ inputs.push-dev }}
    production-project: ${{ vars.DEPOT_PROJECT_PROD }}
    development-project: ${{ vars.DEPOT_PROJECT_DEV }}
```

| Build                     | Mode          | Save in Depot | Publication                         |
| ------------------------- | ------------- | ------------- | ----------------------------------- |
| Pull request              | `dry-run`     | No            | No                                  |
| Release dry-run           | `dry-run`     | Yes           | No                                  |
| Release                   | `release`     | Yes           | After release approval              |
| Trusted development build | `development` | Yes           | `ghcr.io/astral-sh/<name>-dev` only |

Release builds use `ghcr.io/astral-sh/<name>`. Set `dockerhub: true` to also use
`docker.io/astral/<name>`, as uv does. Development publication requires a
same-repository pull request in one of the two Astral repositories and cannot be
combined with a release plan. Each repository supplies its own development Depot
project; release plans in the primary repository, including dry-runs, use the
production project.

The default inventory contains Alpine, Debian slim, and buildpack-deps variants.
Set `image-mappings` to a newline-separated inventory to include additional base
images, Python versions, or DHI images. The action excludes DHI images when
authenticated pulls are disabled, including fork PRs and development-repository
pull-request builds. Use `matrix` for the build matrix and `login` to gate read-only registry
authentication. `publish` is build intent; the publishing workflow must still
enforce its release gates.

## Build the base image

Check out the source and authenticate any private or rate-limited base-image
pulls before invoking `docker-build`.

```yaml
- uses: astral-sh/github-actions/docker-build@<commit-sha>
  id: build
  with:
    name: ruff
    project: ${{ needs.plan.outputs.depot-project-id }}
    images: ${{ needs.plan.outputs.images }}
    mode: ${{ needs.plan.outputs.mode }}
    version: ${{ needs.plan.outputs.version }}
    save: ${{ needs.plan.outputs.save }}
```

`docker-build` returns `build-id` and `digest`. It builds `linux/amd64,linux/arm64`
from the repository root, using `Dockerfile` unless `file` names a variant file.
`save: false` builds without creating a release candidate or
uploading an image record. Saved builds include maximum-mode provenance and an
SBOM, and upload a `docker-image-<name>` artifact containing the build ID, digest,
tags, and index annotations.

The base image's release version must exactly match `[project].version` in
the repository's `pyproject.toml`. A mismatch fails before contacting
Depot. Release tags use PEP 440 full and major/minor versions, with the full
version first for the OCI version label. Stable base releases also get `latest`;
PEP 440 pre-, post-, and development-version releases keep their full version and
do not move the minor or `latest` tags. Development images use SHA tags, and
base-image dry-runs use `dry-run`.

## Build variants

`docker-variant` creates a Dockerfile that copies the selected binaries into
`/usr/local/bin`, clears the inherited entrypoint, and uses the first binary as
the default command.
It also returns the record name and ordered aliases. `docker-build` generates
their tags using the same mode and version as the base image.

```yaml
- uses: astral-sh/github-actions/docker-variant@<commit-sha>
  id: variant
  with:
    image-mapping: alpine:3.23,alpine3.23,alpine
    source-image: registry.depot.dev/${{ needs.plan.outputs.depot-project-id }}@${{ needs.base.outputs.digest }}
    binaries: ruff

- uses: astral-sh/github-actions/docker-build@<commit-sha>
  with:
    name: ${{ steps.variant.outputs.name }}
    project: ${{ needs.plan.outputs.depot-project-id }}
    pull-build-id: ${{ needs.base.outputs.build-id }}
    file: ${{ steps.variant.outputs.file }}
    images: ${{ needs.plan.outputs.images }}
    aliases: ${{ steps.variant.outputs.aliases }}
    mode: ${{ needs.plan.outputs.mode }}
    version: ${{ needs.plan.outputs.version }}
    save: ${{ needs.plan.outputs.save }}
```

For uv, use `binaries: uv uvx` and set `dockerfile-lines` to
`ENV UV_TOOL_BIN_DIR="/usr/local/bin"`. For ty, use `binaries: ty`.
Stable release variants get full-version, major/minor, and unversioned alias
tags. Pre-, post-, and development-version releases get full-version and
unversioned alias tags. The first alias determines the OCI version label. Development
variants get SHA tags with alias suffixes. Dry-run variants use only their
unversioned aliases. Variants never receive an automatic `latest` tag and use the release version
already checked by their base-image build, without needing a source checkout.
In an unsaved pull-request build, omit `pull-build-id` and use the plan's
`ghcr-image` with the `latest` tag as the source image.

## Collect the manifest

After every build finishes, `docker-manifest` downloads the per-image artifacts
and requires exactly the expected base and variant names. It uploads
`docker-manifest.json` and returns its artifact ID.

```yaml
- uses: astral-sh/github-actions/docker-manifest@<commit-sha>
  id: manifest
  with:
    base-name: ruff
    image-mappings: '["alpine:3.23,alpine3.23,alpine"]'
```

The manifest has a `base` record and an `extra` array. Per-image artifacts use
`docker-image-<name>`; the assembled artifact is named `docker-manifest`.

## Publish

The publishing workflow must enforce its own trusted event, branch, repository,
and environment restrictions. Download the manifest by artifact ID, select the
Depot project and allowed destinations independently of its contents, and log in
to those registries. Grant `contents: read`, `id-token: write`, `packages: write`,
and `attestations: write` for GHCR publication and attestations.

```yaml
- uses: astral-sh/github-actions/docker-publish@<commit-sha>
  with:
    project: ${{ vars.DEPOT_PROJECT_PROD }}
    image: ${{ inputs.image }}
    images: ghcr.io/astral-sh/ruff
    attestation-image: ghcr.io/astral-sh/ruff
```

The publisher rejects tags outside the supplied destination list. It verifies
the saved Depot digest, copies the full index to each registry, verifies the
copy, and applies the recorded annotations and tags. It returns the annotated
digest for `attestation-image` and attests both that digest and the original.
Throttled Depot manifest pushes are retried with exponential backoff and jitter.
Publish variants before the base image to keep the base first in GHCR's package
listing.

Run the local contract tests with `python3 -m unittest discover -s tests`.
