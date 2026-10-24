"""Remove superseded workspace artifacts without discarding reusable dependencies."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

FINGERPRINT_DIRECTORY = re.compile(r"^(?P<package>.+)-(?P<fingerprint>[0-9a-f]{16})$")
ARTIFACT_FINGERPRINT = re.compile(r"-([0-9a-f]{16})(?:\.|$)")


def workspace_packages(workspace: Path) -> set[str]:
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"],
            cwd=workspace,
            text=True,
        )
    )
    members = set(metadata["workspace_members"])
    return {
        package["name"] for package in metadata["packages"] if package["id"] in members
    }


def fingerprint_last_used(directory: Path) -> int | None:
    timestamps = [
        fingerprint.stat().st_mtime_ns
        for metadata in directory.glob("*.json")
        if (fingerprint := directory / metadata.stem).is_file()
    ]
    return max(timestamps, default=None)


def prune_workspace_fingerprints(
    profile: Path, marker_timestamp: int, packages: set[str]
) -> tuple[int, int, int]:
    fingerprint_root = profile / ".fingerprint"
    stale_fingerprints_by_package: dict[str, set[str]] = {}
    active_fingerprints: set[str] = set()
    active_packages: set[str] = set()

    for directory in fingerprint_root.iterdir():
        if not directory.is_dir():
            continue

        match = FINGERPRINT_DIRECTORY.fullmatch(directory.name)
        if match is None:
            continue

        last_used = fingerprint_last_used(directory)
        if last_used is None:
            continue

        package = match.group("package")
        fingerprint = match.group("fingerprint")
        if last_used >= marker_timestamp:
            active_fingerprints.add(fingerprint)
            if package in packages:
                active_packages.add(package)
        elif package in packages:
            stale_fingerprints_by_package.setdefault(package, set()).add(fingerprint)

    if not active_fingerprints:
        raise RuntimeError("No active Cargo fingerprints found; refusing to prune")

    stale_fingerprints = {
        fingerprint
        for package in active_packages
        for fingerprint in stale_fingerprints_by_package.get(package, set())
    }
    stale_fingerprints.difference_update(active_fingerprints)
    removed_paths = 0

    for directory in (fingerprint_root, profile / "deps", profile / "build"):
        if not directory.is_dir():
            continue

        for artifact in directory.iterdir():
            match = ARTIFACT_FINGERPRINT.search(artifact.name)
            if match is None or match.group(1) not in stale_fingerprints:
                continue

            if artifact.is_symlink() or artifact.is_file():
                artifact.unlink()
            elif artifact.is_dir():
                shutil.rmtree(artifact)
            else:
                continue

            removed_paths += 1

    return len(stale_fingerprints), removed_paths, len(active_fingerprints)


def prune_all_workspace_artifacts(profile: Path, packages: set[str]) -> int:
    fingerprint_root = profile / ".fingerprint"
    if not fingerprint_root.is_dir():
        return 0
    fingerprints = set()
    for directory in fingerprint_root.iterdir():
        match = FINGERPRINT_DIRECTORY.fullmatch(directory.name)
        if match and match.group("package") in packages:
            fingerprints.add(match.group("fingerprint"))
    removed = 0
    for directory in (fingerprint_root, profile / "deps", profile / "build"):
        if directory.is_dir():
            for artifact in directory.iterdir():
                match = ARTIFACT_FINGERPRINT.search(artifact.name)
                if match and match.group(1) in fingerprints:
                    if artifact.is_symlink() or artifact.is_file():
                        artifact.unlink()
                    elif artifact.is_dir():
                        shutil.rmtree(artifact)
                    removed += 1
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profiles", type=Path, nargs="+", help="Cargo profile directories"
    )
    parser.add_argument("marker", type=Path, help="Marker created before the build")
    parser.add_argument("--dependencies-only", action="store_true")
    args = parser.parse_args()

    marker_timestamp = args.marker.stat().st_mtime_ns
    packages = workspace_packages(Path.cwd())
    for profile in args.profiles:
        if args.dependencies_only:
            removed = sum(
                prune_all_workspace_artifacts(directory.parent, packages)
                for directory in profile.rglob(".fingerprint")
                if directory.is_dir()
            )
            print(f"{profile}: Removed {removed} workspace artifact paths")
            continue
        stale, removed, active = prune_workspace_fingerprints(
            profile, marker_timestamp, packages
        )
        print(
            f"{profile}: Pruned {stale} superseded workspace fingerprints and "
            f"{removed} artifact paths; retained {active} active fingerprints"
        )


if __name__ == "__main__":
    main()
