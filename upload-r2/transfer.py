"""R2 uploads via the S3 API."""

from __future__ import annotations

import mimetypes
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from typing import TYPE_CHECKING

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

    from upload import Upload

MIB = 1024**2
MULTIPART_THRESHOLD = 100_000_000
PART_SIZE = 32 * MIB
UPLOAD_CONCURRENCY = 4
REQUEST_ATTEMPTS = 4
MULTIPART_RESTART_ERRORS = {"InvalidPart", "NoSuchUpload"}


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


def error_code(error: Exception) -> str:
    if isinstance(error, ClientError):
        return error.response["Error"]["Code"]
    return ""


def is_transient_error(error: Exception) -> bool:
    if isinstance(error, ClientError):
        status = error.response["ResponseMetadata"]["HTTPStatusCode"]
        return status in {500, 502, 503, 504} or is_retryable_r2_response(
            status, error_code(error)
        )
    return isinstance(error, (ConnectionError, HTTPClientError))


def object_exists(client: BaseClient, target: dict[str, str]) -> bool:
    try:
        client.head_object(**target)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
            return False
        raise
    return True


def require_missing_object(*, params: dict, **kwargs) -> None:
    params["IfNoneMatch"] = "*"


def upload_file(
    client: BaseClient,
    manager: TransferManager,
    bucket: str,
    upload: Upload,
    *,
    skip_existing: bool,
    cache_control: str,
    content_type: str,
) -> None:
    destination = f"s3://{bucket}/{upload.key}"
    target = {"Bucket": bucket, "Key": upload.key}
    metadata = {}
    if cache_control:
        metadata["CacheControl"] = cache_control
    if not content_type:
        content_type, encoding = mimetypes.guess_type(upload.path.name)
        if encoding:
            content_type = (
                "application/gzip" if encoding == "gzip" else "application/octet-stream"
            )
    if content_type:
        metadata["ContentType"] = content_type

    sessions = 2 if upload.size >= MULTIPART_THRESHOLD else 1
    try:
        if skip_existing and object_exists(client, target):
            print(f"Skipping existing {destination!r}")
            return

        print(f"Uploading {str(upload.path)!r} to {destination!r}")
        for session in range(1, sessions + 1):
            try:
                manager.upload(
                    str(upload.path), bucket, upload.key, extra_args=metadata
                ).result()
                return
            except (BotoCoreError, ClientError) as error:
                code = error_code(error)
                can_restart = (
                    code in MULTIPART_RESTART_ERRORS or is_transient_error(error)
                )
                # A bucket lock can take precedence over the precondition. Check
                # for a committed object after a lock or an ambiguous failure.
                check_destination = can_restart or code == "ObjectLockedByBucketPolicy"
                if skip_existing and (
                    code == "PreconditionFailed"
                    or (check_destination and object_exists(client, target))
                ):
                    print(f"Skipping existing {destination!r}")
                    return
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
    with ExitStack() as stack:
        if skip_existing:
            # s3transfer does not expose IfNoneMatch as an upload argument.
            # Add it to the requests that commit objects for this batch.
            for operation in ("PutObject", "CompleteMultipartUpload"):
                event = f"before-parameter-build.s3.{operation}"
                client.meta.events.register(event, require_missing_object)
                stack.callback(
                    client.meta.events.unregister, event, require_missing_object
                )

        manager = stack.enter_context(TransferManager(client, config))
        executor = stack.enter_context(
            ThreadPoolExecutor(max_workers=UPLOAD_CONCURRENCY)
        )
        worker = partial(
            upload_file,
            client,
            manager,
            bucket,
            skip_existing=skip_existing,
            cache_control=cache_control,
            content_type=content_type,
        )
        for _ in executor.map(worker, uploads):
            pass
