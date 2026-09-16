# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# no-build = true
# exclude-newer = "P7D"
# ///
"""Inject signed executables into Astral release wheels and GitHub archives."""

import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from artifacts import (
    check_archive_binaries,
    find_wheel,
    load_targets,
    read_archive,
    read_wheels,
)


def replace_archive(path: Path, signed: Path, output: Path) -> None:
    """Replace a checked archive's executable bytes and write its new checksum."""
    if path.suffix == ".zip":
        with ZipFile(path) as source, ZipFile(output, "w") as archive:
            archive.comment = source.comment
            for member in source.infolist():
                archive.writestr(
                    member, (signed / PurePosixPath(member.filename).name).read_bytes()
                )
    else:
        with (
            tarfile.open(path, "r:gz") as source,
            tarfile.open(output, "w:gz") as archive,
        ):
            for member in source.getmembers():
                if member.isdir():
                    archive.addfile(member)
                else:
                    contents = (signed / PurePosixPath(member.name).name).read_bytes()
                    member.size = len(contents)
                    archive.addfile(member, io.BytesIO(contents))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(f"{output.name}.sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8"
    )


def assemble(targets: str, prepared: Path, signed: Path, output: Path) -> None:
    """Recheck the original artifacts, then assemble signed wheels and archives."""
    output.mkdir()
    archives = output / "github-archives"
    archives.mkdir()
    for target in load_targets(targets):
        wheels = prepared / "wheels" / target.name
        unsigned = read_wheels(target, wheels)
        source_archive = prepared / "github-archives" / target.github_archive.name
        archive = read_archive(source_archive, target.github_members)
        check_archive_binaries(archive, unsigned)
        target_signed = signed / target.name
        expected = set(unsigned)
        if target.system == "macos":
            expected.add("certificate.pem")
        if {path.name for path in target_signed.iterdir()} != expected:
            raise ValueError(f"Unexpected signed executables for {target.name}")

        destination = output / "wheels" / target.system / target.name
        destination.mkdir(parents=True)
        for wheel in target.wheels:
            source = find_wheel(wheels, wheel.package)
            subprocess.run(
                [
                    sys.executable,
                    Path(__file__).with_name("inject-signed-wheel-binaries.py"),
                    "--input",
                    source,
                    "--output",
                    destination / source.name,
                    "--signed-binaries",
                    target_signed,
                ],
                check=True,
            )
            package = output / "pypi" / wheel.package
            package.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(destination / source.name, package / source.name)
        replace_archive(source_archive, target_signed, archives / source_archive.name)


def main() -> None:
    """Assemble the calling workflow's declared signed artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("signed", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assemble(os.environ["RELEASE_TARGETS"], args.prepared, args.signed, args.output)


if __name__ == "__main__":
    main()
