# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# no-build = true
# ///
"""Verify a directory of packaged native binaries against the signing output."""

import argparse
from pathlib import Path

from verify import verify_native


def main() -> None:
    """Verify every file supplied by the calling project's archive adapter."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("signed", type=Path)
    parser.add_argument("binaries", type=Path)
    args = parser.parse_args()
    binaries = sorted(
        path.relative_to(args.binaries).as_posix()
        for path in args.binaries.rglob("*")
        if path.is_file()
    )
    if not binaries:
        parser.error("No packaged binaries to verify")
    verify_native(args.signed, args.binaries, binaries)


if __name__ == "__main__":
    main()
