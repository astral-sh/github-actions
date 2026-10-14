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
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from artifacts import (
    Target,
    check_archive_binaries,
    read_archive,
    read_wheels,
    write_binaries,
)


def run(*arguments: str | Path) -> str:
    return subprocess.check_output(list(map(str, arguments)), text=True)


def llvm_tool(name: str) -> Path:
    host = next(
        line.removeprefix("host: ")
        for line in run("rustc", "-vV").splitlines()
        if line.startswith("host: ")
    )
    suffix = ".exe" if os.name == "nt" else ""
    tool = (
        Path(run("rustc", "--print", "sysroot").strip())
        / "lib/rustlib"
        / host
        / "bin"
        / (name + suffix)
    )
    if not tool.is_file():
        raise RuntimeError(f"Missing {tool}; install llvm-tools-preview")
    return tool


def binary_identity(binary: Path, system: str) -> dict:
    if system == "windows":
        output = run(llvm_tool("llvm-readobj"), "--coff-debug-directory", binary)
        identifiers = re.findall(r"PDBGUID: \{([\w-]+)\}\s+PDBAge: (\d+)", output)
        if len(identifiers) != 1:
            raise ValueError(f"Expected one PDB identity: {binary}")
        guid, age = identifiers[0]
        return {"guid": guid.upper(), "age": int(age)}
    if system == "macos":
        output = run("xcrun", "dwarfdump", "--uuid", binary)
        identifiers = re.findall(r"UUID: ([\w-]+) \(([^)]+)\)", output)
        if not identifiers:
            raise ValueError(f"Missing Mach-O UUID: {binary}")
        return {
            "uuids": sorted(
                [guid.upper(), architecture] for guid, architecture in identifiers
            )
        }
    raise ValueError(f"Unsupported signing platform: {system}")


def sbom_digest(binary: Path, system: str) -> str:
    """Read and validate the embedded cargo-auditable metadata for signing checks."""
    output = run(llvm_tool("llvm-readobj"), "--sections", binary)
    sections = [
        section
        for section in output.split("Section {")[1:]
        if re.search(r"Name: \.dep-v0(?:\s|$)", section)
    ]
    if not sections:
        raise ValueError(f"Missing embedded SBOM: {binary}")
    if len(sections) != 1:
        raise ValueError(f"Expected one embedded SBOM section: {binary}")
    (section,) = sections
    offset_field, size_field = (
        ("PointerToRawData", "RawDataSize")
        if system == "windows"
        else ("Offset", "Size")
    )
    (offset,) = re.findall(rf"\b{offset_field}: (0x[0-9A-Fa-f]+|\d+)", section)
    (size,) = re.findall(rf"\b{size_field}: (0x[0-9A-Fa-f]+|\d+)", section)
    with binary.open("rb") as stream:
        stream.seek(int(offset, 0))
        data = stream.read(int(size, 0))
    json.loads(zlib.decompress(data))
    return hashlib.sha256(data).hexdigest()


def verify_metadata(
    target: Target, unsigned: Path, signed: Path, packages: list[str]
) -> None:
    """Require debug identities and embedded SBOMs to survive native signing."""
    if not isinstance(packages, list) or any(
        not isinstance(name, str) for name in packages
    ):
        raise TypeError("Metadata packages must be a JSON array of package names")
    declared = {wheel.package for wheel in target.wheels}
    if (
        not packages
        or len(packages) != len(set(packages))
        or not set(packages) <= declared
    ):
        raise ValueError("Metadata packages must be distinct declared wheel packages")
    for wheel in target.wheels:
        if wheel.package not in packages:
            continue
        for name in wheel.binaries:
            if binary_identity(unsigned / name, target.system) != binary_identity(
                signed / name, target.system
            ):
                raise ValueError(f"Signing changed the debug identity: {name}")
            if sbom_digest(unsigned / name, target.system) != sbom_digest(
                signed / name, target.system
            ):
                raise ValueError(f"Signing changed the embedded SBOM: {name}")


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
    packages = json.loads(os.environ.get("METADATA_PACKAGES", "[]"))
    unsigned = os.environ.get("UNSIGNED_DIRECTORY", "")
    if not isinstance(packages, list):
        raise TypeError("Metadata packages must be a JSON array of package names")
    if packages:
        if not unsigned:
            raise ValueError("Metadata verification requires the unsigned directory")
        verify_metadata(target, Path(unsigned), args.signed, packages)
    verify(target, args.signed, args.wheels, args.archives)


if __name__ == "__main__":
    main()
