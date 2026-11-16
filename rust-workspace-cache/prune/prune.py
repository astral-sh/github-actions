"""Remove superseded workspace artifacts without discarding reusable dependencies."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

FINGERPRINT_DIRECTORY = re.compile(r"^(?P<package>.+)-(?P<fingerprint>[0-9a-f]{16})$")
ARTIFACT_FINGERPRINT = re.compile(r"-([0-9a-f]{16})(?:\.|$)")
UNIT_FINGERPRINT = re.compile(r"^[0-9a-f]{16}$")


def is_redirect(path: Path) -> bool:
    """Recognize symlinks and Windows reparse points without following them."""
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def workspace_packages(workspace: Path) -> set[str]:
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"],
            cwd=workspace,
            text=True,
        )
    )
    members = set(metadata["workspace_members"])
    names = {
        package["name"] for package in metadata["packages"] if package["id"] in members
    }
    # Cargo places different versions or sources of a package under the same
    # package name. A unit hash alone cannot distinguish a workspace member from
    # a dependency with that name, so retain both when the lockfile is ambiguous.
    with (Path(metadata["workspace_root"]) / "Cargo.lock").open("rb") as lockfile:
        locked = tomllib.load(lockfile)
    counts = Counter(package["name"] for package in locked.get("package", ()))
    return {name for name in names if counts[name] == 1}


def fingerprint_last_used(directory: Path) -> int | None:
    timestamps = [
        fingerprint.stat().st_mtime_ns
        for metadata in directory.glob("*.json")
        if not is_redirect(metadata)
        and not is_redirect(fingerprint := directory / metadata.stem)
        and fingerprint.is_file()
    ]
    return max(timestamps, default=None)


def validate_profile(target: Path, profile: Path) -> None:
    try:
        relative = profile.relative_to(target)
    except ValueError:
        raise ValueError(
            f"Cargo profile {profile} is outside target directory {target}"
        ) from None
    if not relative.parts:
        raise ValueError("Cargo profile must be below the target directory")
    current = target
    for part in relative.parts:
        if is_redirect(current):
            raise ValueError(f"Refusing to prune symlinked Cargo path or reparse point: {current}")
        current /= part
    if is_redirect(current):
        raise ValueError(f"Refusing to prune symlinked Cargo path or reparse point: {current}")


def prune_workspace_fingerprints(
    profile: Path, marker_timestamp: int, packages: set[str]
) -> tuple[int, int, int]:
    fingerprint_root = profile / ".fingerprint"
    build_root = profile / "build"
    stale_candidates: set[tuple[str, str]] = set()
    active_fingerprints: set[str] = set()
    active_packages: set[str] = set()
    protected_fingerprints: set[str] = set()
    units: list[tuple[str, str, Path]] = []
    legacy_units: set[tuple[str, str]] = set()
    package_directories: set[Path] = set()

    def record(package: str, fingerprint: str, directory: Path) -> None:
        if is_redirect(directory) or not directory.is_dir():
            protected_fingerprints.add(fingerprint)
            return
        last_used = fingerprint_last_used(directory)
        if last_used is None or package not in packages:
            protected_fingerprints.add(fingerprint)
        if last_used is None:
            return
        if last_used >= marker_timestamp:
            active_fingerprints.add(fingerprint)
            if package in packages:
                active_packages.add(package)
        elif package in packages:
            stale_candidates.add((package, fingerprint))

    # Cargo before 1.100 stores all fingerprints in one profile directory.
    if not is_redirect(fingerprint_root) and fingerprint_root.is_dir():
        for directory in fingerprint_root.iterdir():
            match = FINGERPRINT_DIRECTORY.fullmatch(directory.name)
            if match is not None:
                package = match.group("package")
                fingerprint = match.group("fingerprint")
                record(package, fingerprint, directory)
                legacy_units.add((package, fingerprint))

    # Cargo 1.100 stores each compilation unit, including its outputs, under
    # build/<package>/<hash>. Do not follow symlinks supplied by a cache.
    if not is_redirect(build_root) and build_root.is_dir():
        for package_directory in build_root.iterdir():
            if is_redirect(package_directory) or not package_directory.is_dir():
                continue
            for unit in package_directory.iterdir():
                if UNIT_FINGERPRINT.fullmatch(unit.name) is None:
                    continue
                package_directories.add(package_directory)
                if is_redirect(unit) or not unit.is_dir():
                    protected_fingerprints.add(unit.name)
                    continue
                record(package_directory.name, unit.name, unit / "fingerprint")
                units.append((package_directory.name, unit.name, unit))

    if not active_fingerprints:
        raise RuntimeError("No active Cargo fingerprints found; refusing to prune")

    stale_units = {
        (package, fingerprint)
        for package, fingerprint in stale_candidates
        if package in active_packages
        and fingerprint not in active_fingerprints
        and fingerprint not in protected_fingerprints
    }
    stale_fingerprints = {fingerprint for _, fingerprint in stale_units}
    legacy_stale_units = stale_units & legacy_units
    legacy_stale_fingerprints = {fingerprint for _, fingerprint in legacy_stale_units}
    removed_paths = 0

    for package, fingerprint, unit in units:
        if (package, fingerprint) in stale_units:
            shutil.rmtree(unit)
            removed_paths += 1

    for directory in (fingerprint_root, profile / "deps", build_root):
        if is_redirect(directory) or not directory.is_dir():
            continue

        for artifact in directory.iterdir():
            match = ARTIFACT_FINGERPRINT.search(artifact.name)
            if match is None or match.group(1) not in legacy_stale_fingerprints:
                continue
            if directory in (fingerprint_root, build_root):
                fingerprint = FINGERPRINT_DIRECTORY.fullmatch(artifact.name)
                if fingerprint is None or (
                    fingerprint.group("package"), fingerprint.group("fingerprint")
                ) not in legacy_stale_units:
                    continue
                if directory == build_root and artifact in package_directories:
                    # This is a Cargo 1.100 package directory, not a legacy build unit.
                    continue

            if artifact.is_symlink():
                artifact.unlink()
            elif is_redirect(artifact):
                continue
            elif artifact.is_file():
                artifact.unlink()
            elif artifact.is_dir():
                shutil.rmtree(artifact)
            else:
                continue

            removed_paths += 1

    return len(stale_fingerprints), removed_paths, len(active_fingerprints)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profiles", type=Path, nargs="+", help="Cargo profile directories"
    )
    parser.add_argument("marker", type=Path, help="Marker created before the build")
    parser.add_argument("--target-directory", type=Path, required=True)
    args = parser.parse_args()

    marker_timestamp = args.marker.stat().st_mtime_ns
    packages = workspace_packages(Path.cwd())
    for profile in args.profiles:
        validate_profile(args.target_directory, profile)
        stale, removed, active = prune_workspace_fingerprints(
            profile, marker_timestamp, packages
        )
        print(
            f"{profile}: Pruned {stale} superseded workspace fingerprints and "
            f"{removed} artifact paths; retained {active} active fingerprints"
        )


if __name__ == "__main__":
    main()
