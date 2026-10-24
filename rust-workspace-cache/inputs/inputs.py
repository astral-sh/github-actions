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


def checkout_root(workspace: Path) -> Path:
    return Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=workspace, text=True
        ).strip()
    ).resolve()


def build_script_packages(workspace: Path, root: Path) -> dict[str, str]:
    def metadata(manifest: Path) -> dict[Path, dict]:
        result = json.loads(
            subprocess.check_output(
                [
                    "cargo",
                    "metadata",
                    "--no-deps",
                    "--format-version",
                    "1",
                    "--locked",
                    "--manifest-path",
                    str(manifest),
                ],
                cwd=workspace,
            )
        )
        return {
            Path(package["manifest_path"]).resolve(): package
            for package in result["packages"]
        }

    known = metadata(workspace / "Cargo.toml")
    pending = list(known)
    visited = set()
    packages = {}
    while pending:
        manifest = pending.pop().resolve()
        if manifest in visited or not manifest.is_relative_to(root):
            continue
        visited.add(manifest)
        if manifest not in known:
            known.update(metadata(manifest))
        package = known[manifest]
        if any("custom-build" in target["kind"] for target in package["targets"]):
            packages[str(manifest.parent.relative_to(root))] = package["name"]
        for dependency in package["dependencies"]:
            if dependency.get("path"):
                pending.append(Path(dependency["path"]) / "Cargo.toml")
    return packages


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


def scan(workspace: Path) -> dict:
    root = checkout_root(workspace)
    packages = build_script_packages(workspace, root)
    output = (
        subprocess.check_output(["git", "ls-files", "-z", "--", *packages], cwd=root)
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
        "version": 2,
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


def restorable_directories(snapshot: dict) -> set[str]:
    files = {Path(name) for name in snapshot["files"]}
    directories = {Path(name) for name in snapshot["directories"]}
    blocked = set()
    for name, record in snapshot["directories"].items():
        directory = Path(name)
        if any(
            directory / entry not in files
            and not (kind == stat.S_IFDIR and directory / entry in directories)
            for entry, kind in record["entries"]
        ):
            blocked.update([directory, *directory.parents])
    return {name for name in snapshot["directories"] if Path(name) not in blocked}


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


def restore(workspace: Path, saved: dict, profiles: list[Path]) -> dict[str, int]:
    root = checkout_root(workspace)
    if saved["version"] == 1:
        prefix = workspace.relative_to(root)
        saved = saved | {
            "packages": {
                str(prefix / directory): package
                for package, directory in saved["packages"].items()
            },
            **{
                group: {
                    (
                        (prefix / name).as_posix()
                        if group == "files"
                        else str(prefix / name)
                    ): record
                    for name, record in saved[group].items()
                }
                for group in ("files", "directories")
            },
        }
    elif saved["version"] != 2:
        raise ValueError("Unsupported input timestamp manifest")
    current = scan(workspace)
    safe_directories = restorable_directories(current)
    changed_paths = set()
    matching = {"files": [], "directories": []}
    for group, key in [("files", "identity"), ("directories", "entries")]:
        for name in current[group].keys() | saved[group].keys():
            previous = saved[group].get(name)
            record = current[group].get(name)
            if record and previous and record[key] == previous[key]:
                if group != "directories" or name in safe_directories:
                    matching[group].append(name)
            else:
                changed_paths.add(name)
    changed_packages = {
        package
        for directory, package in current["packages"].items()
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
