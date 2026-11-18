"""R2 uploads via the S3 API."""

from __future__ import annotations

import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from typing import TYPE_CHECKING
from uuid import uuid4

import botocore.session
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionError,
    HTTPClientError,
)
from s3transfer.manager import TransferConfig, TransferManager

if TYPE_CHECKING:
    from botocore.awsrequest import AWSResponse
    from botocore.client import BaseClient

    from .upload import Upload

MIB = 1024**2
MULTIPART_THRESHOLD = 100_000_000
PART_SIZE = 32 * MIB
UPLOAD_CONCURRENCY = 4
REQUEST_ATTEMPTS = 4
MULTIPART_RESTART_ERRORS = {"InvalidPart", "NoSuchUpload"}
WRITE_ID_METADATA_KEY = "upload-r2-write-id"

# Use the backfill tool's media types plus NDJSON for release metadata.
EXTENSION_CONTENT_TYPES = (
    (".tar.gz", "application/gzip"),
    (".tar.zst", "application/zstd"),
    (".tar.bz2", "application/x-bzip2"),
    (".zip", "application/zip"),
    (".gz", "application/gzip"),
    (".zst", "application/zstd"),
    (".exe", "application/octet-stream"),
    (".msi", "application/octet-stream"),
    (".dmg", "application/octet-stream"),
    (".pkg", "application/octet-stream"),
    (".sh", "application/x-shellscript"),
    (".ps1", "application/x-powershell"),
    (".ndjson", "application/x-ndjson"),
    (".sha256", "text/plain"),
    (".sum", "text/plain"),
)


def content_type_for_filename(filename: str) -> str:
    for extension, content_type in EXTENSION_CONTENT_TYPES:
        if filename.endswith(extension):
            return content_type
    return "application/octet-stream"


def retry_delay(attempt: int) -> float:
    return random.uniform(0.5, 1) * 2 ** (attempt - 1)


def is_retryable_r2_response(status: int, code: str) -> bool:
    return status == 429 or (
        status == 400 and code in {"ClientDisconnect", "IncompleteBody"}
    )


def retry_r2_request(
    *, response: tuple[AWSResponse, dict] | None, attempts: int, **kwargs
) -> float | None:
    # Botocore handles transport errors and ordinary 5xx responses. Add the R2
    # responses it can otherwise treat as permanent, using the same attempt limit.
    if response is None or attempts >= REQUEST_ATTEMPTS:
        return None
    http_response, parsed = response
    if is_retryable_r2_response(
        http_response.status_code, parsed.get("Error", {}).get("Code", "")
    ):
        return retry_delay(attempts)
    return None


def make_client(account_id: str) -> BaseClient:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required")

    client = botocore.session.get_session().create_client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path", "payload_signing_enabled": True},
            request_checksum_calculation="when_required",
            retries={"mode": "standard", "total_max_attempts": REQUEST_ATTEMPTS},
        ),
    )
    client.meta.events.register("needs-retry.s3", retry_r2_request)
    return client


def is_transient_error(error: Exception) -> bool:
    if isinstance(error, ClientError):
        status = error.response["ResponseMetadata"]["HTTPStatusCode"]
        return status in {500, 502, 503, 504} or is_retryable_r2_response(
            status, error.response["Error"]["Code"]
        )
    return isinstance(error, (ConnectionError, HTTPClientError))


def head_object(client: BaseClient, target: dict[str, str]) -> dict | None:
    try:
        return client.head_object(**target)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
            return None
        raise


def add_write_condition(
    expected_etags: dict[str, str | None], *, params: dict, **kwargs
) -> None:
    etag = expected_etags[params["Key"]]
    if etag is None:
        params["IfNoneMatch"] = "*"
    else:
        params["IfMatch"] = etag


def upload_file(
    client: BaseClient,
    manager: TransferManager,
    bucket: str,
    upload: Upload,
    *,
    expected_etags: dict[str, str | None],
    skip_existing: bool,
    cache_control: str,
    content_type: str,
) -> None:
    destination = f"s3://{bucket}/{upload.key}"
    target = {"Bucket": bucket, "Key": upload.key}
    metadata: dict[str, str | dict[str, str]] = {
        "ContentType": content_type or content_type_for_filename(upload.path.name),
    }
    if cache_control:
        metadata["CacheControl"] = cache_control

    sessions = 2 if upload.size >= MULTIPART_THRESHOLD else 1
    try:
        existing = head_object(client, target)
        if skip_existing and existing is not None:
            print(f"Skipping existing {destination!r}")
            return

        etag = existing.get("ETag") if existing is not None else None
        if existing is not None and not etag:
            raise RuntimeError(f"HeadObject returned no ETag for {destination!r}")
        # Keep the same condition through request retries and multipart restarts.
        expected_etags[upload.key] = etag
        write_id = None if skip_existing else uuid4().hex
        if write_id is not None:
            metadata["Metadata"] = {WRITE_ID_METADATA_KEY: write_id}

        print(f"Uploading {str(upload.path)!r} to {destination!r}")
        for session in range(1, sessions + 1):
            try:
                manager.upload(
                    str(upload.path), bucket, upload.key, extra_args=metadata
                ).result()
                return
            except (BotoCoreError, ClientError) as error:
                code = (
                    error.response["Error"]["Code"]
                    if isinstance(error, ClientError)
                    else None
                )
                can_restart = code in MULTIPART_RESTART_ERRORS or is_transient_error(
                    error
                )
                # A bucket lock can take precedence over the precondition. Check
                # for a committed object after a lock or an ambiguous failure.
                check_destination = can_restart or code == "ObjectLockedByBucketPolicy"
                if skip_existing and (
                    code == "PreconditionFailed"
                    or (check_destination and head_object(client, target) is not None)
                ):
                    print(f"Skipping existing {destination!r}")
                    return
                if write_id is not None and (
                    check_destination or code == "PreconditionFailed"
                ):
                    current = head_object(client, target)
                    if current is not None and (
                        current.get("Metadata", {}).get(WRITE_ID_METADATA_KEY)
                        == write_id
                    ):
                        print(f"Confirmed upload to {destination!r}")
                        return
                    current_etag = (
                        current.get("ETag", "") if current is not None else None
                    )
                    if code == "PreconditionFailed" or current_etag != etag:
                        raise RuntimeError(
                            f"Upload conflict for {destination!r}: "
                            "the destination changed during the upload"
                        ) from error
                if session == sessions or not can_restart:
                    raise
                print(f"Restarting multipart upload for {destination!r}: {error}")
                time.sleep(retry_delay(1))
    except (BotoCoreError, ClientError, OSError) as error:
        raise RuntimeError(f"Upload failed for {destination!r}: {error}") from error


def upload_files(
    client: BaseClient,
    bucket: str,
    uploads: list[Upload],
    *,
    skip_existing: bool,
    cache_control: str,
    content_type: str = "",
) -> None:
    if not uploads:
        return

    config = TransferConfig(
        multipart_threshold=MULTIPART_THRESHOLD,
        multipart_chunksize=PART_SIZE,
        max_request_concurrency=UPLOAD_CONCURRENCY,
    )
    expected_etags: dict[str, str | None] = {}
    apply_condition = partial(add_write_condition, expected_etags)
    with ExitStack() as stack:
        # s3transfer does not expose conditional headers as upload arguments.
        # Look up each key's condition on the requests that commit the object.
        for operation in ("PutObject", "CompleteMultipartUpload"):
            event = f"before-parameter-build.s3.{operation}"
            client.meta.events.register(event, apply_condition)
            stack.callback(client.meta.events.unregister, event, apply_condition)

        manager = stack.enter_context(TransferManager(client, config))
        executor = stack.enter_context(
            ThreadPoolExecutor(max_workers=UPLOAD_CONCURRENCY)
        )
        worker = partial(
            upload_file,
            client,
            manager,
            bucket,
            expected_etags=expected_etags,
            skip_existing=skip_existing,
            cache_control=cache_control,
            content_type=content_type,
        )
        for _ in executor.map(worker, uploads):
            pass
