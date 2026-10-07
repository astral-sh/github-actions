#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# no-build = true
# exclude-newer = "P7D"
# ///

"""Merge named review job results into one GitHub pull request review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import PurePosixPath
from typing import Any, TextIO


def without_mentions(text: str) -> str:
    lines = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker[0], len(marker)
            elif (
                marker[0] == fence[0]
                and len(marker) >= fence[1]
                and not line[match.end() :].strip()
            ):
                fence = None
            lines.append(line)
        elif fence is not None:
            lines.append(line)
        else:
            lines.append(re.sub(r"(?<![A-Za-z0-9_.])@(?=[A-Za-z0-9])", "@\u200b", line))
    return "".join(lines)


def review_comment(finding: dict[str, Any]) -> dict[str, Any]:
    location = finding["code_location"]
    path = PurePosixPath(location["relative_file_path"])
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        msg = f"invalid repository-relative path: {path}"
        raise ValueError(msg)

    side = location["side"]
    if side not in {"LEFT", "RIGHT"}:
        msg = f"invalid diff side: {side}"
        raise ValueError(msg)

    line_range = location["line_range"]
    start = line_range["start"]
    end = line_range["end"]
    if start < 1 or end < start:
        msg = f"invalid line range: {start}-{end}"
        raise ValueError(msg)

    title = re.sub(r"^(?:\[P[0-3]\]\s*)+", "", finding["title"])
    comment: dict[str, Any] = {
        "path": str(path),
        "line": end,
        "side": side,
        "body": f"**[P{finding['priority']}] {title}**\n\n{finding['body']}",
    }
    if start != end:
        comment["start_line"] = start
        comment["start_side"] = side
    return comment


def review_payload(reviews: dict[str, Any], commit_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_id):
        msg = "commit ID must be a full Git commit SHA"
        raise ValueError(msg)

    findings: dict[str, tuple[int, dict[str, Any], list[str]]] = {}
    statuses = []
    incomplete = False
    for name, job in reviews.items():
        status = job["result"]
        statuses.append(f"- {name}: {status}")
        if status == "skipped":
            continue
        if status in {"failure", "cancelled"}:
            incomplete = True
            continue
        if status != "success":
            msg = f"unexpected review job result for {name}: {status}"
            raise ValueError(msg)

        review = json.loads(job["outputs"]["result"])
        if not isinstance(review["findings"], list):
            msg = f"findings from {name} must be an array"
            raise TypeError(msg)
        for finding in review["findings"]:
            priority = finding["priority"]
            if type(priority) is not int or not 0 <= priority <= 3:
                msg = f"invalid finding priority from {name}: {priority}"
                raise ValueError(msg)
            comment = review_comment(finding)
            key = json.dumps(comment, sort_keys=True)
            if key not in findings:
                findings[key] = priority, comment, []
            sources = findings[key][2]
            if name not in sources:
                sources.append(name)

    body = "Review results:\n\n" + "\n".join(statuses)
    if incomplete:
        body += (
            "\n\nThis review is incomplete; findings only include successful reviews."
        )

    comments = []
    for _, comment, sources in sorted(findings.values(), key=lambda item: item[0]):
        comments.append(
            {
                **comment,
                "body": without_mentions(
                    f"{comment['body']}\n\n_Review: {', '.join(sources)}._"
                ),
            }
        )

    return {
        "commit_id": commit_id,
        "event": "COMMENT",
        "body": without_mentions(body),
        "comments": comments,
    }


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit-id", required=True, help="the pull request head commit SHA"
    )
    args = parser.parse_args()

    reviews = json.load(stdin)
    json.dump(review_payload(reviews, args.commit_id), stdout, indent=2)
    stdout.write("\n")


if __name__ == "__main__":
    main()
