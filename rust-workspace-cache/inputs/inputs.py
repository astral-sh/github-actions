"""Restore matching build-script package inputs after a fresh Git checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

FINGERPRINT = re.compile(r"^(?P<package>.+)-[0-9a-f]{16}$")


def build_script_packages(root: Path) -> dict[str, str]:
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"],
            cwd=root,
        )
    )
    members = set(metadata["workspace_members"])
    return {
        package["name"]: str(Path(package["manifest_path"]).parent.relative_to(root))
        for package in metadata["packages"]
        if package["id"] in members
        and any("custom-build" in target["kind"] for target in package["targets"])
        and Path(package["manifest_path"]).is_relative_to(root)
    }


def safe_path(root: Path, name: str) -> Path | None:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Invalid cached input path: {name}")
    path = root / relative
    return path if path.resolve().is_relative_to(root) else None


def identity(path: Path) -> list[str | int] | None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        return None
    return [hashlib.sha256(path.read_bytes()).hexdigest(), stat.S_IMODE(info.st_mode)]


def directory_entries(path: Path) -> list[list[str | int]]:
    return sorted(
        [entry.name, stat.S_IFMT(entry.lstat().st_mode)] for entry in path.iterdir()
    )


def scan(root: Path) -> dict:
    packages = build_script_packages(root)
    output = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", *packages.values()], cwd=root
        )
        if packages
        else b""
    )
    files = {}
    directories = set()
    for name in sorted({os.fsdecode(name) for name in output.split(b"\0") if name}):
        path = safe_path(root, name)
        if path is None or not path.exists():
            continue
        value = identity(path)
        if value is None:
            continue
        files[name] = {"identity": value, "mtime_ns": path.stat().st_mtime_ns}
        for parent in path.parents:
            if parent == root:
                break
            directories.add(parent)
    return {
        "version": 1,
        "packages": packages,
        "files": files,
        "directories": {
            str(path.relative_to(root)): {
                "entries": directory_entries(path),
                "mtime_ns": path.stat().st_mtime_ns,
            }
            for path in sorted(directories)
        },
    }


def invalidate_build_scripts(profiles: list[Path], packages: set[str]) -> int:
    removed = 0
    for profile in profiles:
        fingerprints = profile / ".fingerprint"
        if not fingerprints.is_dir():
            continue
        for directory in fingerprints.iterdir():
            match = FINGERPRINT.fullmatch(directory.name)
            if (
                match
                and match.group("package") in packages
                and directory.is_dir()
                and not directory.is_symlink()
                and any(directory.glob("run-build-script-*"))
            ):
                output = profile / "build" / directory.name
                if output.is_symlink():
                    output.unlink()
                elif output.is_dir():
                    shutil.rmtree(output)
                shutil.rmtree(directory)
                removed += 1
    return removed


def restore(root: Path, saved: dict, profiles: list[Path]) -> dict[str, int]:
    if saved["version"] != 1:
        raise ValueError("Unsupported input timestamp manifest")
    current = scan(root)
    changed_paths = set()
    matching = {"files": [], "directories": []}
    for group, key in [("files", "identity"), ("directories", "entries")]:
        for name in current[group].keys() | saved[group].keys():
            previous = saved[group].get(name)
            record = current[group].get(name)
            if record and previous and record[key] == previous[key]:
                matching[group].append(name)
            else:
                changed_paths.add(name)
    changed_packages = {
        package
        for package, directory in current["packages"].items()
        if any(Path(name).is_relative_to(directory) for name in changed_paths)
    }
    # Changed tracked inputs or directory listings must rerun their build scripts
    # even with preserved mtimes or a clock behind the cached build's timestamp.
    invalidated = invalidate_build_scripts(profiles, changed_packages)
    for group, names in matching.items():
        for name in names:
            path = safe_path(root, name)
            if path is None or path.is_symlink():
                continue
            os.utime(
                path,
                ns=(path.stat().st_atime_ns, saved[group][name]["mtime_ns"]),
                follow_symlinks=os.utime not in os.supports_follow_symlinks,
            )
    # Refresh stat information so a later forced checkout does not rewrite
    # unchanged files merely because their timestamps were restored.
    subprocess.run(
        [
            "git",
            "update-index",
            "-q",
            "--ignore-submodules",
            "--ignore-missing",
            "--refresh",
        ],
        cwd=root,
        check=True,
    )
    return {
        "restored_files": len(matching["files"]),
        "restored_directories": len(matching["directories"]),
        "changed_packages": len(changed_packages),
        "invalidated_build_scripts": invalidated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["save", "restore"])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("profiles", type=Path, nargs="*")
    args = parser.parse_args()
    start = time.monotonic()
    if args.operation == "save":
        data = scan(Path.cwd())
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(data, separators=(",", ":")) + "\n")
        result = {"saved_files": len(data["files"])}
    elif args.manifest.exists():
        if not args.profiles:
            parser.error("restore requires at least one Cargo profile directory")
        result = restore(
            Path.cwd(), json.loads(args.manifest.read_text()), args.profiles
        )
    else:
        result = {"no_manifest": True}
    print(
        json.dumps(
            result | {"operation": args.operation, "seconds": time.monotonic() - start}
        )
    )


if __name__ == "__main__":
    main()
