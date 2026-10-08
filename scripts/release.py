# /// script
# requires-python = ">=3.12"
# dependencies = ["packaging"]
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

from packaging.version import InvalidVersion, Version


CALVER = re.compile(r"([0-9]{4})\.([0-9]{2})\.([0-9]{2})\.(0|[1-9][0-9]*)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate"))
    parser.add_argument(
        "version",
        nargs="?",
        help="YYYY.MM.DD.N; defaults to today's next generation (prepare) or the prepared version (validate)",
    )
    args = parser.parse_args()

    if args.action == "prepare" and not args.version:
        today = datetime.datetime.now(datetime.UTC).strftime("%Y.%m.%d")
        tags = subprocess.run(
            ["git", "tag", "--list", f"{today}.*"],
            stdout=subprocess.PIPE, text=True, check=True,
        )
        generations = (
            int(tag_match.group(4))
            for tag in tags.stdout.splitlines()
            if (tag_match := CALVER.fullmatch(tag))
        )
        args.version = f"{today}.{max(generations, default=-1) + 1}"

    if args.action == "validate":
        with Path("pyproject.toml").open("rb") as file:
            prepared_text = tomllib.load(file)["project"]["version"]
        try:
            prepared = Version(prepared_text)
        except InvalidVersion as error:
            parser.error(f"invalid version in pyproject.toml: {error}")
        if len(prepared.release) != 4:
            parser.error(f"no prepared CalVer release in pyproject.toml (version is {prepared_text!r})")
        if not args.version:
            year, month, day, generation = prepared.release
            args.version = f"{year:04}.{month:02}.{day:02}.{generation}"

    match = CALVER.fullmatch(args.version)
    if match is None:
        parser.error("version must be YYYY.MM.DD.N, with N a non-negative integer (0 for the first release)")
    try:
        datetime.date(*(int(part) for part in match.group(1, 2, 3)))
    except ValueError as error:
        parser.error(f"invalid release date: {error}")

    if args.action == "prepare":
        subprocess.run(
            ["uv", "version", "--frozen", args.version],
            stdout=subprocess.DEVNULL, check=True,
        )
    else:
        # uv normalizes the version as PEP 440; Git tags keep CalVer's padded date.
        if prepared != Version(args.version):
            parser.error(f"pyproject.toml version {prepared_text!r} does not match requested release {args.version!r}")

        tag = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{args.version}"],
            stdout=subprocess.DEVNULL,
            check=False,
        )
        if tag.returncode == 0:
            parser.error(f"tag {args.version} already exists")
        if tag.returncode != 1:
            tag.check_returncode()

    print(f"version={args.version}")


if __name__ == "__main__":
    main()
