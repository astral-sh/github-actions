# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# no-build = true
# exclude-newer = "P7D"
# ///
"""Prepare and validate the repository's CalVer releases."""

import argparse
import datetime
import re
import subprocess
import tomllib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate"))
    parser.add_argument("version", help="YYYY.MM.DD, or YYYY.MM.DD.N for a later release that day")
    args = parser.parse_args()

    match = re.fullmatch(
        r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})(?:\.([1-9][0-9]*))?",
        args.version,
    )
    if match is None:
        parser.error("version must be YYYY.MM.DD[.N], with N a positive integer")
    try:
        datetime.date(*(int(part) for part in match.group(1, 2, 3)))
    except ValueError as error:
        parser.error(f"invalid release date: {error}")

    if args.action == "prepare":
        subprocess.run(["uv", "version", "--frozen", args.version], check=True)
        return

    # uv normalizes the version as PEP 440; Git tags keep CalVer's padded date.
    expected = ".".join(str(int(part)) for part in match.groups() if part is not None)
    with Path("pyproject.toml").open("rb") as file:
        prepared = tomllib.load(file)["project"]["version"]
    if prepared != expected:
        parser.error(f"pyproject.toml version {prepared!r} does not match requested release {args.version!r}")

    tag = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{args.version}"],
        stdout=subprocess.DEVNULL,
        check=False,
    )
    if tag.returncode == 0:
        parser.error(f"tag {args.version} already exists")
    if tag.returncode != 1:
        tag.check_returncode()


if __name__ == "__main__":
    main()
