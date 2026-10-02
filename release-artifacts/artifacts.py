"""Read the declared wheel and GitHub archive contents for Astral releases."""

import hashlib
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


@dataclass(frozen=True)
class Wheel:
    """One wheel package and its executable inventory for a release target."""

    package: str
    directory: Path
    binaries: list[str]


@dataclass(frozen=True)
class Target:
    """Artifact paths and expected executables for one release target."""

    name: str
    system: str
    wheels: list[Wheel]
    github_archive: Path
    github_members: list[str]

    @classmethod
    def from_dict(cls, value: dict) -> "Target":
        """Read a target declaration supplied by the calling workflow."""
        return cls(
            name=value["target"],
            system=value["system"],
            wheels=[
                Wheel(wheel["package"], Path(wheel["directory"]), wheel["binaries"])
                for wheel in value["wheels"]
            ],
            github_archive=Path(value["github-archive"]),
            github_members=value["github-archive-members"],
        )


def load_targets(value: str) -> list[Target]:
    """Read the release targets passed to preparation or assembly."""
    return [Target.from_dict(target) for target in json.loads(value)]


def find_wheel(directory: Path, package: str) -> Path:
    """Require exactly one wheel for the given package in a directory."""
    wheels = sorted(directory.glob(f"{package}-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected one {package} wheel in {directory}")
    return wheels[0]


def read_wheel(path: Path, binaries: list[str]) -> dict[str, bytes]:
    """Read the wheel's .data/scripts members, requiring the declared inventory."""
    found = {}
    with ZipFile(path) as archive:
        for member in archive.infolist():
            _, scripts, binary = member.filename.partition(".data/scripts/")
            if not scripts:
                continue
            if not binary or "/" in binary or "\\" in binary or binary in found:
                raise ValueError(
                    f"Unexpected executable wheel member: {member.filename}"
                )
            found[binary] = archive.read(member)
    if set(found) != set(binaries):
        raise ValueError(f"Unexpected executables in {path.name}: {sorted(found)}")
    return found


def read_wheels(target: Target, directory: Path | None = None) -> dict[str, bytes]:
    """Read every declared wheel and require distinct executable names."""
    binaries = {}
    paths = []
    for wheel in target.wheels:
        path = find_wheel(directory or wheel.directory, wheel.package)
        paths.append(path)
        contents = read_wheel(path, wheel.binaries)
        if binaries.keys() & contents.keys():
            raise ValueError(f"Duplicate executable names in {target.name}'s wheels")
        binaries.update(contents)
    if directory is not None and set(directory.glob("*.whl")) != set(paths):
        raise ValueError(f"Unexpected wheels in {directory}")
    return binaries


def read_archive(path: Path, members: list[str]) -> dict[str, bytes]:
    """Check an archive's checksum and exact file layout, then read its executables."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_name(f"{path.name}.sha256").read_text(encoding="utf-8")
    # Windows' sha256sum marks binary-mode input with an asterisk.
    if checksum.replace(" *", "  ").split() != [digest, path.name]:
        raise ValueError(f"Archive checksum differs from input: {path.name}")

    expected = {member: PurePosixPath(member).name for member in members}
    if len(expected) != len(members) or len(set(expected.values())) != len(members):
        raise ValueError("Archive executable names must be distinct")
    if path.suffix == ".zip":
        with ZipFile(path) as archive:
            if sorted(archive.namelist()) != sorted(expected):
                raise ValueError(f"Unexpected release archive contents: {path.name}")
            return {binary: archive.read(member) for member, binary in expected.items()}

    if not path.name.endswith(".tar.gz"):
        raise ValueError(f"Unsupported release archive: {path.name}")
    directories = {
        str(parent)
        for member in members
        for parent in PurePosixPath(member).parents
        if str(parent) != "."
    }
    with tarfile.open(path, "r:gz") as archive:
        files = [
            member
            for member in archive.getmembers()
            if not (member.name in directories and member.isdir())
        ]
        if sorted(member.name for member in files) != sorted(expected) or any(
            not member.isfile() for member in files
        ):
            raise ValueError(f"Unexpected release archive contents: {path.name}")
        binaries = {}
        for member in files:
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Missing archive executable: {member.name}")
            with source:
                binaries[expected[member.name]] = source.read()
        return binaries


def check_archive_binaries(archive: dict[str, bytes], wheels: dict[str, bytes]) -> None:
    """Require every GitHub archive executable to match the corresponding wheel."""
    for name, contents in archive.items():
        if contents != wheels[name]:
            raise ValueError(f"Archive executable differs from wheel: {name}")


def write_binaries(directory: Path, binaries: dict[str, bytes]) -> None:
    """Write executables to a new directory with executable access."""
    directory.mkdir(parents=True)
    for name, contents in binaries.items():
        binary = directory / name
        binary.write_bytes(contents)
        binary.chmod(0o755)
