# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# no-build = true
# exclude-newer = "P7D"
# ///
"""Build native release signing matrices and artifact declarations."""

import json
import os
import tomllib
from pathlib import Path, PurePosixPath

PLATFORMS = {
    "macos": {
        "aarch64-apple-darwin": ("namespace-profile-macos-15", "arm64"),
        "x86_64-apple-darwin": ("namespace-profile-macos-15", "x64"),
    },
    "windows": {
        "aarch64-pc-windows-msvc": (
            "github-windows-11-aarch64-8",
            "arm64",
        ),
        "i686-pc-windows-msvc": (
            "namespace-profile-windows-2022-x86-64-16x32",
            "x86",
        ),
        "x86_64-pc-windows-msvc": (
            "namespace-profile-windows-2022-x86-64-16x32",
            "x64",
        ),
    },
}

SIGNED_TARGET_SUFFIXES = ("-apple-darwin", "-pc-windows-msvc")


def release_targets(workspace: Path) -> list[str]:
    """Read and validate the target inventory used by cargo-dist."""
    targets = tomllib.loads(workspace.read_text(encoding="utf-8"))["dist"]["targets"]
    if (
        not isinstance(targets, list)
        or not all(isinstance(target, str) for target in targets)
        or len(targets) != len(set(targets))
    ):
        raise ValueError("dist.targets must be an array of unique strings")
    return targets


def package_inventories(value: str) -> dict[str, dict[str, list[str]]]:
    """Read and validate the caller's per-system wheel inventories."""
    packages = json.loads(value)
    if not isinstance(packages, dict) or not packages:
        raise ValueError("packages must be a non-empty object")
    if unknown := packages.keys() - PLATFORMS.keys():
        raise ValueError(f"Unknown signing systems: {sorted(unknown)}")

    for system, inventory in packages.items():
        if not isinstance(inventory, dict) or not inventory:
            raise ValueError(f"{system} packages must be a non-empty object")
        binaries = []
        for package, package_binaries in inventory.items():
            if not isinstance(package, str) or not package:
                raise ValueError(f"{system} package names must be non-empty strings")
            if (
                not isinstance(package_binaries, list)
                or not package_binaries
                or not all(
                    isinstance(binary, str) and binary for binary in package_binaries
                )
                or len(package_binaries) != len(set(package_binaries))
            ):
                raise ValueError(
                    f"{system} package {package} must declare unique executables"
                )
            binaries.extend(package_binaries)
        if len(binaries) != len(set(binaries)):
            raise ValueError(f"{system} package executables must be distinct")
    return packages


def artifact_inputs(
    system: str,
    target: str,
    packages: dict[str, dict[str, list[str]]],
    archive_package: str,
    wheels_directory: PurePosixPath,
    github_archives_directory: PurePosixPath,
) -> dict:
    """Declare wheel packages and exact GitHub archive members for one target."""
    inventory = packages[system]
    if archive_package not in inventory:
        raise ValueError(f"Missing {archive_package} from {system} packages")

    extension = "tar.gz" if system == "macos" else "zip"
    archive_stem = f"{archive_package}-{target}"
    return {
        "system": system,
        "wheels": [
            {
                "package": package,
                "directory": str(wheels_directory / target),
                "binaries": binaries,
            }
            for package, binaries in inventory.items()
        ],
        "github-archive": str(
            github_archives_directory / f"{archive_stem}.{extension}"
        ),
        "github-archive-members": [
            f"{archive_stem}/{binary}" if system == "macos" else binary
            for binary in inventory[archive_package]
        ],
    }


def signing_plan(
    targets: list[str],
    packages: dict[str, dict[str, list[str]]],
    archive_package: str,
    wheels_directory: PurePosixPath,
    github_archives_directory: PurePosixPath,
) -> dict[str, list[dict]]:
    """Require every macOS and Windows target to have a native verifier."""
    expected = {target for target in targets if target.endswith(SIGNED_TARGET_SUFFIXES)}
    configured = {target for platforms in PLATFORMS.values() for target in platforms}
    if unsupported := expected - configured:
        raise ValueError(f"Unsupported release signing targets: {sorted(unsupported)}")

    plan = {}
    for system, platforms in PLATFORMS.items():
        system_targets = [target for target in platforms if target in expected]
        if system_targets and system not in packages:
            raise ValueError(f"Missing package inventory for {system}")
        plan[system] = [
            {
                "target": target,
                "runner": platforms[target][0],
                "python-architecture": platforms[target][1],
                **artifact_inputs(
                    system,
                    target,
                    packages,
                    archive_package,
                    wheels_directory,
                    github_archives_directory,
                ),
            }
            for target in system_targets
        ]
    return plan


def main() -> None:
    """Print cargo-dist targets, native matrices, and artifact declarations."""
    targets = release_targets(Path(os.environ["RELEASE_WORKSPACE"]))
    packages = package_inventories(os.environ["RELEASE_PACKAGES"])
    plan = signing_plan(
        targets,
        packages,
        os.environ["RELEASE_ARCHIVE_PACKAGE"],
        PurePosixPath(os.environ["RELEASE_WHEELS_DIRECTORY"]),
        PurePosixPath(os.environ["RELEASE_GITHUB_ARCHIVES_DIRECTORY"]),
    )

    print(f"targets={json.dumps(targets, separators=(',', ':'))}")
    for system, platforms in plan.items():
        print(f"{system}={json.dumps(platforms, separators=(',', ':'))}")
    artifacts = [target for platforms in plan.values() for target in platforms]
    print(f"artifacts={json.dumps(artifacts, separators=(',', ':'))}")


if __name__ == "__main__":
    main()
