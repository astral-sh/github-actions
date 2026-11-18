"""Validate the upload plan and dispatch it to R2."""

import os
import re
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

MAX_OBJECT_SIZE = 5 * 1024**4 - 5 * 1024**3


@dataclass(frozen=True)
class Upload:
    path: Path
    key: str
    size: int


def plan_uploads(directory: Path, include: str, prefix: str) -> list[Upload]:
    if not directory.is_dir():
        raise ValueError(f"Source directory does not exist: {str(directory)!r}")
    root = directory.resolve()
    selected = set()
    for line in include.splitlines():
        pattern = line.strip()
        if not pattern:
            continue
        relative = Path(pattern)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Expected a relative path inside the source: {pattern!r}")
        if any(char in pattern for char in "*?["):
            selected.update(path for path in root.glob(pattern) if path.is_file())
        else:
            path = root / relative
            if not path.is_file():
                raise ValueError(f"Required file is missing: {pattern!r}")
            selected.add(path)

    if not selected:
        raise ValueError("No files matched include")

    uploads = []
    for path in sorted(selected):
        relative = path.relative_to(root).as_posix()
        if path.resolve() != path:
            raise ValueError(f"Upload path goes through a symbolic link: {relative!r}")
        key = prefix + relative
        if len(key.encode("utf-8")) > 1024:
            raise ValueError(f"Object key exceeds R2's 1024-byte limit: {key!r}")
        size = path.stat().st_size
        if size > MAX_OBJECT_SIZE:
            raise ValueError(f"File exceeds R2's upload size limit: {relative!r}")
        uploads.append(Upload(path, key, size))
    return uploads


def main() -> None:
    account = os.environ["R2_ACCOUNT_ID"]
    bucket = os.environ["R2_BUCKET"]
    if not re.fullmatch(r"[0-9a-f]{32}", account, re.IGNORECASE | re.ASCII):
        raise ValueError("account-id must be a 32-character hexadecimal string")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise ValueError("bucket must be a valid R2 bucket name")
    source = os.environ["R2_SOURCE_DIRECTORY"]
    if not source:
        raise ValueError("source-directory is required")
    prefix = os.environ["R2_PREFIX"]
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    if_exists = os.environ["R2_IF_EXISTS"]
    if if_exists not in {"skip", "overwrite"}:
        raise ValueError("if-exists must be skip or overwrite")
    dry_run = os.environ["R2_DRY_RUN"]
    if dry_run not in {"true", "false"}:
        raise ValueError("dry-run must be true or false")

    uploads = plan_uploads(Path(source), os.environ["R2_INCLUDE"], prefix)
    if dry_run == "true":
        for upload in uploads:
            destination = f"s3://{bucket}/{upload.key}"
            print(f"Would upload {str(upload.path)!r} to {destination!r}")
        return

    from transfer import make_client, upload_files

    with closing(make_client(account)) as client:
        upload_files(
            client,
            bucket,
            uploads,
            skip_existing=if_exists == "skip",
            cache_control=os.environ["R2_CACHE_CONTROL"],
            content_type=os.environ.get("R2_CONTENT_TYPE", ""),
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        sys.exit(f"Upload to R2 failed: {error}")
