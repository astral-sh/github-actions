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
import tempfile
import time
from pathlib import Path

FINGERPRINT = re.compile(r"^(?P<package>.+)-[0-9a-f]{16}$")


def workspace_packages(root: Path) -> list[dict]:
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"],
            cwd=root,
        )
    )
    members = set(metadata["workspace_members"])
    return [package for package in metadata["packages"] if package["id"] in members]


def source_layout(root: Path, target: Path) -> str | None:
    # Cargo checks only inputs from the previous compilation. A new sibling
    # module can change resolution without changing any of those files.
    paths = ["."]
    if target != root and target.is_relative_to(root):
        paths.append(f":(exclude,literal){target.relative_to(root).as_posix()}")
    command = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    listing = subprocess.run([*command, "--", *paths], cwd=root, capture_output=True)
    if listing.returncode:
        return None
    digest = hashlib.sha256()
    for name in sorted(set(listing.stdout.split(b"\0")) - {b""}):
        path = root / os.fsdecode(name)
        try:
            mode = path.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            continue
        kind = stat.S_IFMT(mode)
        digest.update(name + b"\0" + kind.to_bytes(4, "big"))
        if stat.S_ISLNK(kind):
            digest.update(os.fsencode(os.readlink(path)) + b"\0")
        elif stat.S_ISDIR(kind):
            # Git lists submodules as directories. Inspect initialized ones.
            if (path / ".git").exists():
                nested = source_layout(path, target)
                if nested is None:
                    return None
                digest.update(nested.encode())
            elif any(path.iterdir()):
                return None
    return digest.hexdigest()


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


def scan(root: Path, target: Path | None = None) -> dict:
    members = workspace_packages(root)
    layout = source_layout(root, root / (target or "target"))
    packages = {
        package["name"]: str(Path(package["manifest_path"]).parent.relative_to(root))
        for package in members
        if any("custom-build" in target["kind"] for target in package["targets"])
        and Path(package["manifest_path"]).is_relative_to(root)
    }
    output = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", *packages.values()], cwd=root
        )
        if packages and layout is not None
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
        "workspace": [package["name"] for package in members],
        "source_layout": layout,
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


def invalidate_units(
    profiles: list[Path], packages: set[str], *, build_scripts_only: bool
) -> int:
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
                and (not build_scripts_only or any(directory.glob("run-build-script-*")))
            ):
                output = profile / "build" / directory.name
                if output.is_symlink():
                    output.unlink()
                elif output.is_dir():
                    shutil.rmtree(output)
                shutil.rmtree(directory)
                removed += 1
    return removed


def restore(
    root: Path, saved: dict, profiles: list[Path], target: Path | None = None
) -> dict[str, int]:
    if saved["version"] != 1:
        raise ValueError("Unsupported input timestamp manifest")
    current = scan(root, target)
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
        for package, directory in current["packages"].items()
        if any(Path(name).is_relative_to(directory) for name in changed_paths)
    }
    # Changed tracked inputs or directory listings must rerun their build scripts
    # even with preserved mtimes or a clock behind the cached build's timestamp.
    invalidated = invalidate_units(profiles, changed_packages, build_scripts_only=True)
    invalidated_workspace = 0
    if (
        current["source_layout"] is None
        or current["source_layout"] != saved.get("source_layout")
    ):
        invalidated_workspace = invalidate_units(
            profiles, set(current["workspace"]), build_scripts_only=False
        )
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
    if current["source_layout"] is not None:
        subprocess.run(
            [
                "git", "update-index", "-q", "--ignore-submodules",
                "--ignore-missing", "--refresh",
            ],
            cwd=root,
            check=True,
        )
    return {
        "restored_files": len(matching["files"]),
        "restored_directories": len(matching["directories"]),
        "changed_packages": len(changed_packages),
        "invalidated_build_scripts": invalidated,
        "invalidated_workspace_units": invalidated_workspace,
    }


def move_tool_directory(source: Path, destination: Path) -> bool:
    try:
        mode = source.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(mode):
        raise ValueError(f"Expected a tool-owned directory at {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        # The target and RUNNER_TEMP can be on different volumes. Finish the
        # transfer before replacing the destination, without following its links.
        incoming = Path(temporary) / "incoming"
        shutil.move(source, incoming)
        previous = Path(temporary) / "previous"
        try:
            if os.path.lexists(destination):
                destination.rename(previous)
            incoming.rename(destination)
        except OSError:
            if os.path.lexists(previous):
                previous.rename(destination)
            shutil.move(incoming, source)
            raise
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["save", "restore"])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("profiles", type=Path, nargs="*")
    parser.add_argument("--target-directory", type=Path)
    parser.add_argument("--extra-target-directory", type=Path)
    args = parser.parse_args()
    start = time.monotonic()
    if args.operation == "save":
        data = scan(Path.cwd(), args.target_directory)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(data, separators=(",", ":")) + "\n")
        result = {"saved_files": len(data["files"])}
    elif args.manifest.exists():
        if not args.profiles:
            parser.error("restore requires at least one Cargo profile directory")
        result = restore(
            Path.cwd(),
            json.loads(args.manifest.read_text()),
            args.profiles,
            args.target_directory,
        )
    else:
        result = {"no_manifest": True}
        if any((profile / ".fingerprint").is_dir() for profile in args.profiles):
            packages = {package["name"] for package in workspace_packages(Path.cwd())}
            result["invalidated_workspace_units"] = invalidate_units(
                args.profiles, packages, build_scripts_only=False
            )
    if extra := args.extra_target_directory:
        staged = args.manifest.with_name(f"target-{extra.name}")
        source, destination = (extra, staged) if args.operation == "save" else (staged, extra)
        if move_tool_directory(source, destination):
            result["tool_directory"] = extra.name
    print(
        json.dumps(
            result | {"operation": args.operation, "seconds": time.monotonic() - start}
        )
    )


if __name__ == "__main__":
    main()
