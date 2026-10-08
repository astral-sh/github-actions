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
            prepared = tomllib.load(file)["project"]["version"]
        if not args.version:
            parts = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)", prepared)
            if parts is None:
                parser.error(f"no prepared CalVer release in pyproject.toml (version is {prepared!r})")
            year, month, day, generation = map(int, parts.groups())
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
        expected = ".".join(str(int(part)) for part in match.groups())
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

    print(f"version={args.version}")


if __name__ == "__main__":
    main()
