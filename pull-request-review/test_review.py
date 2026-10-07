"""Exercise the review-to-comment pipeline without contacting GitHub."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent / "scripts"
HEAD_SHA = "a" * 40


def finding(*, side: str = "RIGHT", start: int = 3, end: int = 3) -> dict:
    return {
        "title": "[P3] Explain the invariant",
        "body": "Ask @reviewer.\n\n```text\n@literal\n```",
        "priority": 3,
        "code_location": {
            "relative_file_path": "src/example.rs",
            "side": side,
            "line_range": {"start": start, "end": end},
        },
    }


class ReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "output"
        self.calls = self.root / "calls"
        self.posts = self.root / "posts"
        self.env = {
            **os.environ,
            "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
            "RUNNER_TEMP": str(self.root),
            "GITHUB_OUTPUT": str(self.output),
            "HEAD_SHA": HEAD_SHA,
            "PULL_REQUEST_NUMBER": "42",
            "GITHUB_REPOSITORY": "owner/repository",
            "MOCK_HEAD_SHA": HEAD_SHA,
            "MOCK_CALLS": str(self.calls),
            "MOCK_POSTS": str(self.posts),
            "MOCK_READ_STATUS": "0",
            "MOCK_POST_STATUS": "0",
        }
        gh = self.root / "gh"
        gh.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$MOCK_CALLS"
case "$1" in
  pr)
    printf '%s\\n' "$MOCK_HEAD_SHA"
    exit "$MOCK_READ_STATUS"
    ;;
  api)
    cat >> "$MOCK_POSTS"
    exit "$MOCK_POST_STATUS"
    ;;
  *) exit 99 ;;
esac
"""
        )
        gh.chmod(0o755)

    def run_script(self, name: str, result: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPTS / name)],
            env={**self.env, "REVIEW_RESULT": json.dumps(result)},
            capture_output=True,
            text=True,
            check=False,
        )

    def prepare(self, review: dict) -> dict:
        self.output.write_text("")
        result = self.run_script("prepare.sh", review)
        self.assertEqual(result.returncode, 0, result.stderr)
        header, body = self.output.read_text().split("\n", 1)
        delimiter = header.removeprefix("result<<")
        self.assertTrue(body.endswith(f"{delimiter}\n"))
        return json.loads(body.removesuffix(f"{delimiter}\n"))

    def test_prepare_and_publish_findings(self) -> None:
        comments = self.prepare(
            {"findings": [finding(), finding(side="LEFT", start=5, end=8)]}
        )
        result = self.run_script("publish.sh", comments)
        self.assertEqual(result.returncode, 0, result.stderr)
        post_command = "api --method POST repos/owner/repository/pulls/42/comments --input - --silent"
        self.assertEqual(
            self.calls.read_text().splitlines(),
            [
                "pr view 42 --repo owner/repository --json headRefOid --jq .headRefOid",
                post_command,
                post_command,
            ],
        )
        posts = [json.loads(line) for line in self.posts.read_text().splitlines()]
        self.assertEqual(posts, comments["comments"])
        self.assertEqual(
            posts[0],
            {
                "commit_id": HEAD_SHA,
                "path": "src/example.rs",
                "line": 3,
                "side": "RIGHT",
                "body": "**[P3] Explain the invariant**\n\nAsk @\u200breviewer.\n\n```text\n@literal\n```",
            },
        )
        self.assertEqual(posts[1]["start_line"], 5)
        self.assertEqual(posts[1]["line"], 8)
        self.assertEqual(posts[1]["start_side"], "LEFT")

    def test_security_metadata_does_not_change_comments(self) -> None:
        review = {"findings": [finding()]}
        self.assertEqual(
            self.prepare(review),
            self.prepare({**review, "reviewed_paths": ["src/example.rs"]}),
        )

    def test_empty_findings_do_not_contact_github(self) -> None:
        result = self.run_script("publish.sh", self.prepare({"findings": []}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls.exists())

    def test_stale_head_does_not_publish(self) -> None:
        self.env["MOCK_HEAD_SHA"] = "b" * 40
        result = self.run_script("publish.sh", self.prepare({"findings": [finding()]}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertFalse(self.posts.exists())

    def test_failed_head_lookup_does_not_publish(self) -> None:
        self.env["MOCK_READ_STATUS"] = "1"
        result = self.run_script("publish.sh", self.prepare({"findings": [finding()]}))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.posts.exists())

    def test_failed_post_stops_publishing(self) -> None:
        self.env["MOCK_POST_STATUS"] = "1"
        result = self.run_script(
            "publish.sh", self.prepare({"findings": [finding(), finding()]})
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.posts.read_text().splitlines()), 1)

    def test_invalid_finding_is_rejected(self) -> None:
        invalid = finding()
        invalid["code_location"]["relative_file_path"] = "../outside.rs"
        result = self.run_script("prepare.sh", {"findings": [invalid]})
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
