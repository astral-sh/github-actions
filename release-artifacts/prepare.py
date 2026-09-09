# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# no-build = true
# exclude-newer = "P7D"
# ///
"""Prepare signing inputs after checking wheel and GitHub archive agreement."""

import argparse
import os
import shutil
from pathlib import Path

from artifacts import (
    check_archive_binaries,
    find_wheel,
    load_targets,
    read_archive,
    read_wheels,
    write_binaries,
)


def prepare(targets: str, output: Path) -> None:
    """Stage original artifacts and one unsigned executable directory per target."""
    output.mkdir()
    archives = output / "github-archives"
    archives.mkdir()
    for target in load_targets(targets):
        binaries = read_wheels(target)
        archive = read_archive(target.github_archive, target.github_members)
        check_archive_binaries(archive, binaries)
        write_binaries(output / "unsigned" / target.system / target.name, binaries)
        wheels = output / "wheels" / target.name
        wheels.mkdir(parents=True)
        for wheel in target.wheels:
            source = find_wheel(wheel.directory, wheel.package)
            shutil.copyfile(source, wheels / source.name)
        for path in (
            target.github_archive,
            target.github_archive.with_name(f"{target.github_archive.name}.sha256"),
        ):
            shutil.copyfile(path, archives / path.name)


def main() -> None:
    """Prepare the calling workflow's declared artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(os.environ["RELEASE_TARGETS"], args.output)


if __name__ == "__main__":
    main()
