# Docker build and publication

Build multi-platform images with Depot, save immutable release candidates, and
publish them later without rebuilding. These actions work with uv, Ruff, and ty;
the calling repository owns its Dockerfile, Depot projects, release policy,
registry credentials, image matrix, and tag rules.

Use Linux runners with Docker, Bash, and `jq`. Grant build jobs
`contents: read` and `id-token: write`, and configure the selected Depot project's
[GitHub Actions OIDC trust](https://depot.dev/docs/container-builds/integrations/github-actions).
Production and development builds should use separate Depot projects. Pin each
action reference to a reviewed commit.

## Build the base image

Check out the source and authenticate any private or rate-limited base-image
pulls before invoking `docker-build`.

```yaml
- uses: astral-sh/github-actions/docker-build@<commit-sha>
  id: build
  with:
    name: ruff
    project: ${{ vars.DEPOT_PROJECT_PROD }}
    images: ghcr.io/astral-sh/ruff
    save: true
    tags: |
      type=pep440,pattern={{ version }},value=${{ inputs.version }}
      type=pep440,pattern={{ major }}.{{ minor }},value=${{ inputs.version }}
```

`docker-build` returns `build-id` and `digest`. Its default platforms are
`linux/amd64,linux/arm64`; `context`, `file`, `platforms`, and metadata `flavor`
can be overridden. `save: false` builds without creating a release candidate or
uploading an image record. Saved builds include maximum-mode provenance and an
SBOM, and upload a `docker-image-<name>` artifact containing the build ID, digest,
tags, and index annotations.

## Build variants

`docker-variant` creates a Dockerfile that copies the selected binaries into
`/usr/local/bin`, clears the inherited entrypoint, and sets the default command.
It also returns the record name and release tag rules for each image alias.

```yaml
- uses: astral-sh/github-actions/docker-variant@<commit-sha>
  id: variant
  with:
    image-mapping: alpine:3.23,alpine3.23,alpine
    source-image: registry.depot.dev/${{ vars.DEPOT_PROJECT_PROD }}@${{ needs.base.outputs.digest }}
    binaries: ruff
    command: ruff
    version: ${{ inputs.version }}

- uses: astral-sh/github-actions/docker-build@<commit-sha>
  with:
    name: ${{ steps.variant.outputs.name }}
    project: ${{ vars.DEPOT_PROJECT_PROD }}
    pull-build-id: ${{ needs.base.outputs.build-id }}
    file: ${{ steps.variant.outputs.file }}
    images: ghcr.io/astral-sh/ruff
    tags: ${{ steps.variant.outputs.tags }}
    flavor: latest=false
    save: true
```

For uv, use `binaries: uv uvx`, `command: uv`, and set `dockerfile-lines` to
`ENV UV_TOOL_BIN_DIR="/usr/local/bin"`. For ty, use `binaries: ty` and
`command: ty`. `push-dev: true` produces SHA-based variant tags. In an unsaved
pull-request build, omit `pull-build-id` and use a published base-image reference.

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

The manifest has a `base` record and an `extra` array. `artifact-prefix` can be
set consistently on `docker-build` and `docker-manifest` when a workflow builds
more than one product. The manifest artifact name defaults to `docker-manifest`.

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
Publish variants before the base image to keep the base first in GHCR's package
listing.

Run the local contract tests with `python3 -m unittest discover -s tests`.
