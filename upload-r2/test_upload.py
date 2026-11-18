import os
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from botocore.awsrequest import AWSResponse
from botocore.exceptions import ConnectionClosedError
from botocore.stub import ANY, Stubber
from urllib3.response import HTTPResponse

import transfer
from upload import plan_uploads

BUCKET = "mirror"
PREFIX = "github/project/releases/download/v1/"
CACHE_CONTROL = "public, max-age=31536000, immutable"
METADATA = {"CacheControl": CACHE_CONTROL, "ContentType": "application/zip"}
MISSING_OBJECT = (404, {}, b"")
DISCONNECT = b"<Error><Code>ClientDisconnect</Code></Error>"
MULTIPART_PART_SIZE = 5 * transfer.MIB
MULTIPART_CONTENT = b"a" * MULTIPART_PART_SIZE + b"ef"
MULTIPART_SETTINGS = {
    "MULTIPART_THRESHOLD": len(MULTIPART_CONTENT),
    "PART_SIZE": MULTIPART_PART_SIZE,
    "UPLOAD_CONCURRENCY": 1,
}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with patch.dict(
            os.environ,
            {"AWS_ACCESS_KEY_ID": "test-key", "AWS_SECRET_ACCESS_KEY": "test-secret"},
        ):
            self.client = transfer.make_client("a" * 32)
        self.addCleanup(self.client.close)
        self.s3 = self.enterContext(Stubber(self.client))
        self.addCleanup(self.s3.assert_no_pending_responses)
        self.enterContext(patch.multiple(transfer, **MULTIPART_SETTINGS))
        self.enterContext(patch("transfer.time.sleep"))

    def asset(self, name, content=b"release asset"):
        (self.directory / name).write_bytes(content)
        return {"Bucket": BUCKET, "Key": PREFIX + name}

    def upload(self, *, include="*.zip"):
        transfer.upload_files(
            self.client,
            BUCKET,
            plan_uploads(self.directory, include, PREFIX),
            skip_existing=True,
            cache_control=CACHE_CONTROL,
        )

    def expect_missing_object(self, target):
        self.s3.add_client_error(
            "head_object", http_status_code=404, expected_params=target
        )

    def multipart_attempt(self, target, upload_id, completion_error=None):
        self.s3.add_response(
            "create_multipart_upload", {"UploadId": upload_id}, {**target, **METADATA}
        )
        request = {**target, "UploadId": upload_id}
        parts = []
        for number in (1, 2):
            etag = f'"part-{number}"'
            self.s3.add_response(
                "upload_part",
                {"ETag": etag},
                {**request, "PartNumber": number, "Body": ANY},
            )
            parts.append({"PartNumber": number, "ETag": etag})
        completion = {
            **request,
            "MultipartUpload": {"Parts": parts},
        }
        if completion_error is None:
            self.s3.add_response("complete_multipart_upload", {}, completion)
        else:
            code, status = completion_error
            self.s3.add_client_error(
                "complete_multipart_upload",
                service_error_code=code,
                http_status_code=status,
                expected_params=completion,
            )
        return request

    def test_partial_rerun_only_uploads_missing_keys(self):
        first = self.asset("a.zip")
        last = self.asset("b.zip")
        put_first = {**first, **METADATA, "Body": ANY}
        put_last = {**last, **METADATA, "Body": ANY}
        self.expect_missing_object(first)
        self.s3.add_response("put_object", {}, put_first)
        self.expect_missing_object(last)
        self.s3.add_client_error(
            "put_object",
            service_error_code="AccessDenied",
            http_status_code=403,
            expected_params=put_last,
        )
        with self.assertRaisesRegex(RuntimeError, r"b\.zip.*AccessDenied"):
            self.upload()

        self.s3.add_response("head_object", {}, first)
        self.expect_missing_object(last)
        self.s3.add_response("put_object", {}, put_last)
        self.upload()

        self.s3.add_response("head_object", {}, first)
        self.s3.add_response("head_object", {}, last)
        self.upload()

    def test_gzip_archive_uses_the_compressed_content_type(self):
        target = self.asset("archive.tar.gz")
        self.expect_missing_object(target)
        self.s3.add_response(
            "put_object",
            {},
            {
                **target,
                "CacheControl": CACHE_CONTROL,
                "ContentType": "application/gzip",
                "Body": ANY,
            },
        )

        self.upload(include="archive.tar.gz")

    def test_invalid_part_restarts_the_entire_upload(self):
        target = self.asset("large.zip", MULTIPART_CONTENT)
        self.expect_missing_object(target)
        request = self.multipart_attempt(target, "failed", ("InvalidPart", 400))
        self.s3.add_response("abort_multipart_upload", {}, request)
        self.expect_missing_object(target)
        self.multipart_attempt(target, "replacement")

        self.upload()

    def test_invalid_part_skips_committed_object(self):
        target = self.asset("large.zip", MULTIPART_CONTENT)
        self.expect_missing_object(target)
        request = self.multipart_attempt(target, "committed", ("InvalidPart", 400))
        self.s3.add_response("abort_multipart_upload", {}, request)
        self.s3.add_response(
            "head_object", {"ContentLength": len(MULTIPART_CONTENT)}, target
        )

        self.upload()

    def test_multipart_retries_are_bounded(self):
        target = self.asset("large.zip", MULTIPART_CONTENT)
        self.expect_missing_object(target)
        for upload_id in ("first", "second"):
            request = self.multipart_attempt(target, upload_id, ("InvalidPart", 400))
            self.s3.add_response("abort_multipart_upload", {}, request)
            self.expect_missing_object(target)

        with self.assertRaisesRegex(RuntimeError, "InvalidPart"):
            self.upload()

    def test_concurrent_multipart_write_hits_bucket_lock(self):
        target = self.asset("large.zip", MULTIPART_CONTENT)
        self.expect_missing_object(target)
        request = self.multipart_attempt(
            target, "racing", ("ObjectLockedByBucketPolicy", 409)
        )
        self.s3.add_response("abort_multipart_upload", {}, request)
        self.s3.add_response(
            "head_object", {"ContentLength": len(MULTIPART_CONTENT)}, target
        )

        self.upload()

    def test_bucket_lock_without_an_existing_key_is_an_error(self):
        target = self.asset("a.zip")
        self.expect_missing_object(target)
        self.s3.add_client_error(
            "put_object",
            service_error_code="ObjectLockedByBucketPolicy",
            http_status_code=409,
            expected_params={**target, **METADATA, "Body": ANY},
        )
        self.expect_missing_object(target)
        with self.assertRaisesRegex(RuntimeError, "ObjectLockedByBucketPolicy"):
            self.upload()

    def test_precondition_failure_skips_a_concurrent_write(self):
        target = self.asset("a.zip")
        self.expect_missing_object(target)
        self.s3.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
            expected_params={**target, **METADATA, "Body": ANY},
        )
        self.upload()


class HTTPRetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.directory / "release.zip").write_bytes(b"abcdef")
        self.requests = []
        self.enterContext(patch("botocore.endpoint.time.sleep"))
        with patch.dict(
            os.environ,
            {"AWS_ACCESS_KEY_ID": "test-key", "AWS_SECRET_ACCESS_KEY": "test-secret"},
        ):
            self.client = self.enterContext(closing(transfer.make_client("a" * 32)))

    def upload(self, responses, *, skip_existing=True):
        responses = iter(responses)

        def respond(request):
            body = request.body
            if hasattr(body, "read"):
                body = body.read()
            self.requests.append((request, body))
            result = next(responses)
            if result is None:
                raise ConnectionClosedError(endpoint_url=request.url)
            status, headers, body = result
            return AWSResponse(
                request.url,
                status,
                headers,
                HTTPResponse(body=BytesIO(body), preload_content=False),
            )

        with patch.object(
            self.client._endpoint.http_session, "send", side_effect=respond
        ):
            transfer.upload_files(
                self.client,
                BUCKET,
                plan_uploads(self.directory, "*.zip", PREFIX),
                skip_existing=skip_existing,
                cache_control=CACHE_CONTROL,
            )
        self.assertEqual(list(responses), [])

    def test_retries_head_and_rewinds_a_single_put(self):
        self.upload(
            [
                (503, {}, b"<Error><Code>ServiceUnavailable</Code></Error>"),
                (429, {}, b"<Error><Code>TooManyRequests</Code></Error>"),
                MISSING_OBJECT,
                (400, {}, b"<Error><Code>IncompleteBody</Code></Error>"),
                (400, {}, DISCONNECT),
                (200, {"etag": '"release"'}, b""),
            ]
        )
        self.assertEqual(
            [request.method for request, _ in self.requests],
            ["HEAD", "HEAD", "HEAD", "PUT", "PUT", "PUT"],
        )
        for request, body in self.requests[3:]:
            self.assertEqual(request.headers["If-None-Match"], b"*")
            self.assertEqual(body, b"abcdef")

    def test_persistent_throttling_stops_at_request_limit(self):
        throttled = (429, {}, b"<Error><Code>TooManyRequests</Code></Error>")
        with self.assertRaisesRegex(RuntimeError, "TooManyRequests"):
            self.upload([throttled] * transfer.REQUEST_ATTEMPTS)
        self.assertEqual(
            [request.method for request, _ in self.requests],
            ["HEAD"] * transfer.REQUEST_ATTEMPTS,
        )

    def test_overwrite_writes_unconditionally_without_lookup(self):
        uploaded = (200, {"etag": '"release"'}, b"")
        self.upload([MISSING_OBJECT, uploaded])
        self.upload([uploaded], skip_existing=False)

        self.assertEqual(
            [request.method for request, _ in self.requests], ["HEAD", "PUT", "PUT"]
        )
        self.assertEqual(self.requests[1][0].headers["If-None-Match"], b"*")
        self.assertNotIn("If-None-Match", self.requests[2][0].headers)

    def test_lost_put_response_recovers_a_locked_object(self):
        self.upload(
            [
                MISSING_OBJECT,
                None,  # The first PUT committed and its response was lost.
                (409, {}, b"<Error><Code>ObjectLockedByBucketPolicy</Code></Error>"),
                (503, {}, b""),
                (200, {"content-length": "6"}, b""),
            ]
        )
        self.assertEqual(
            [request.method for request, _ in self.requests],
            ["HEAD", "PUT", "PUT", "HEAD", "HEAD"],
        )

    def test_retries_a_part_and_recovers_a_lost_completion_response(self):
        (self.directory / "release.zip").write_bytes(MULTIPART_CONTENT)
        missing_upload = b"<Error><Code>NoSuchUpload</Code></Error>"
        with patch.multiple(transfer, **MULTIPART_SETTINGS):
            self.upload(
                [
                    MISSING_OBJECT,
                    (
                        200,
                        {},
                        b"<InitiateMultipartUploadResult><UploadId>committed</UploadId></InitiateMultipartUploadResult>",
                    ),
                    (400, {}, DISCONNECT),
                    (200, {"etag": '"part-1"'}, b""),
                    (200, {"etag": '"part-2"'}, b""),
                    None,  # R2 committed the object and closed the connection.
                    (404, {}, missing_upload),
                    (404, {}, missing_upload),
                    (200, {"content-length": str(len(MULTIPART_CONTENT))}, b""),
                ]
            )
        self.assertEqual(
            [request.method for request, _ in self.requests],
            ["HEAD", "POST", "PUT", "PUT", "PUT", "POST", "POST", "DELETE", "HEAD"],
        )
        for request, body in self.requests[2:4]:
            self.assertIn("partNumber=1", request.url)
            self.assertEqual(body, MULTIPART_CONTENT[:MULTIPART_PART_SIZE])
        for request, _ in self.requests[5:7]:
            self.assertTrue(request.url.endswith("?uploadId=committed"))
            self.assertEqual(request.headers["If-None-Match"], b"*")


class PlanTests(unittest.TestCase):
    def test_selects_unique_files_and_preserves_subdirectories(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "nested").mkdir()
            (source / "nested" / "asset.zip").write_bytes(b"asset")
            (source / "checksum.txt").write_text("checksum")
            (source / "unused.bin").touch()
            uploads = plan_uploads(
                source, "**/*.zip\nnested/asset.zip\nchecksum.txt\n*.tar.gz", PREFIX
            )
            self.assertEqual(
                [(upload.key, upload.size) for upload in uploads],
                [(PREFIX + "checksum.txt", 8), (PREFIX + "nested/asset.zip", 5)],
            )

    def test_missing_literal_fails_even_when_glob_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "present.zip").touch()
            with self.assertRaisesRegex(ValueError, "Required file is missing"):
                plan_uploads(source, "*.zip\nmissing.zip", PREFIX)

    def test_rejects_symlink_and_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.zip"
            outside.touch()
            source = root / "source"
            source.mkdir()
            (source / "link.zip").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                plan_uploads(source, "*.zip", PREFIX)
            with self.assertRaisesRegex(ValueError, "inside the source"):
                plan_uploads(source, "../*.zip", PREFIX)
