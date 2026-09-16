# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# no-build = true
# exclude-newer = "P7D"
# ///
"""Verify signed wheels and a GitHub archive with the native platform tools."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from artifacts import (
    Target,
    check_archive_binaries,
    read_archive,
    read_wheels,
    write_binaries,
)


def verify_native(signed: Path, directory: Path, binaries: list[str]) -> None:
    """Require exact signed bytes and native signature verification for each file."""
    if sys.platform == "darwin":
        command = [
            "uv",
            "run",
            "--locked",
            Path(__file__).with_name("verify-release-binaries-macos.py"),
            signed,
            directory,
            *binaries,
        ]
    elif sys.platform == "win32":
        command = [
            "pwsh",
            "-NoProfile",
            "-File",
            Path(__file__).with_name("verify-release-binaries-windows.ps1"),
            "-Signed",
            signed,
            "-BinaryDirectory",
            directory,
            "-BinariesJson",
            json.dumps(binaries),
        ]
    else:
        raise ValueError("Native release verification requires macOS or Windows")
    subprocess.run(command, check=True)


def verify(target: Target, signed: Path, wheels: Path, archives: Path) -> None:
    """Extract both formats and verify their inventories, byte equality, and signatures."""
    binaries = read_wheels(target, wheels)
    archive = read_archive(archives / target.github_archive.name, target.github_members)
    check_archive_binaries(archive, binaries)
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as temporary:
        directory = Path(temporary)
        for name, contents in (("wheels", binaries), ("github", archive)):
            extracted = directory / name
            write_binaries(extracted, contents)
            verify_native(signed, extracted, sorted(contents))


def main() -> None:
    """Verify the target selected by the calling workflow's native matrix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("signed", type=Path)
    parser.add_argument("wheels", type=Path)
    parser.add_argument("archives", type=Path)
    args = parser.parse_args()
    target = Target.from_dict(json.loads(os.environ["RELEASE_TARGET"]))
    verify(target, args.signed, args.wheels, args.archives)


if __name__ == "__main__":
    main()
