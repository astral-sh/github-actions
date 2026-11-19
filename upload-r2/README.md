# Upload to R2

Upload files from a local directory to a Cloudflare R2 bucket. Each object key
combines the optional prefix and the file's relative path.

```yaml
- name: Mirror versioned release assets
  uses: astral-sh/github-actions/upload-r2@<release-commit-sha>
  env:
    AWS_ACCESS_KEY_ID: ${{ secrets.MIRROR_R2_ACCESS_KEY_ID }}
    AWS_SECRET_ACCESS_KEY: ${{ secrets.MIRROR_R2_SECRET_ACCESS_KEY }}
  with:
    account-id: ${{ secrets.MIRROR_R2_CLOUDFLARE_ACCOUNT_ID }}
    bucket: ${{ secrets.MIRROR_R2_BUCKET_NAME }}
    prefix: github/project/releases/download/${{ inputs.tag }}
    source-directory: artifacts
    include: |
      *.zip
      *.zip.sha256
      *.tar.gz
      *.tar.gz.sha256
      sha256.sum
      *.sh
      *.ps1
    cache-control: public, max-age=31536000, immutable
```

| Input | Description |
| --- | --- |
| `source-directory` | Required. Local directory, relative to the action step's working directory or absolute. The source directory and selected files must be outside `GITHUB_ACTION_PATH`. |
| `include` | Newline-separated relative paths or glob patterns. Defaults to `**/*`. Each literal path must exist. A glob may match zero files, but the selection as a whole must contain at least one file. Matched files must be reachable without following symlinks inside the source directory. |
| `account-id` | Required. Cloudflare account ID. |
| `bucket` | Required. R2 bucket name. |
| `prefix` | Optional. Key prefix. The action adds a trailing slash when needed. |
| `if-exists` | `skip` (default) checks existing objects and uploads missing keys. `overwrite` replaces objects conditionally. |
| `cache-control` | Optional. Sets the `Cache-Control` metadata on uploaded objects. |
| `content-type` | Optional. Sets the same `Content-Type` on every uploaded object. The default uses the release mirror's extension map, with `application/x-ndjson` for `.ndjson` and `application/octet-stream` for unknown extensions. |
| `dry-run` | Set to `"true"` to validate and print the local upload plan without R2 credentials. Both modes use the action's locked uv environment. |
| `uv-version` | uv version installed by `setup-uv`. Defaults to the version pinned in [action.yml](action.yml). |
| `enable-cache` | Defaults to `"false"`. Set to `"true"` to cache uv dependencies across GitHub Actions runs. The cache key uses this action's `uv.lock`. |

For live uploads, pass R2 object read and write credentials for the bucket
using the standard AWS SDK environment variables `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`. Set `AWS_SESSION_TOKEN` for temporary R2 credentials.

The default mode checks each target key with `HeadObject` and uses conditional
writes to protect against concurrent uploads of the same key. Rerun a versioned
upload with the same release files. For an existing object, the action checks
the size and prefers CRC64/NVME, falling back to CRC32. For composite CRC32, it
looks up the stored first part's size with a second `HeadObject` and reads the
local file using that part size. A size or checksum mismatch fails the upload
step. When R2 supplies neither checksum, the action logs that verification is
unavailable and skips the existing key.

In `overwrite` mode, R2 replaces an object only if its ETag at commit matches
the ETag read before uploading. If the action found no object, R2 creates it
only if the key is still absent at commit. The action reports conflicts by key
and keeps the original condition across retries. If the response to a write
is lost, the action checks a write ID in the object's metadata to confirm
whether its upload succeeded.

The action switches from single PUTs to multipart uploads at 100 MB
(100,000,000 bytes). Multipart uploads can retry individual parts.
[R2 upload guidance](https://developers.cloudflare.com/r2/objects/upload-objects/#choose-an-upload-method)

Transient errors during object checks and uploads get up to four attempts per
request with backoff, including R2 throttling and interrupted request bodies.
If a multipart upload needs a fresh upload ID, the action can restart it once.
In `skip` mode it checks for an existing object before restarting, which also
handles a successful completion whose response was lost.

For mutable installer aliases, set `if-exists: overwrite` and select the exact
installer filenames. Set the prefix to `installers/<project>/latest` and
`cache-control` to `public, max-age=300`. Gate this step on stable releases in
the caller. If a checksum manifest must be published last, upload it in a
subsequent step after the archives succeed.

Run the tests locally with
`uv run --locked --project upload-r2 python -B -m unittest discover -s upload-r2 -v`.
