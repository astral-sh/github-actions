"""Prepare Rust cache keys and cache only job-installed Cargo binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()[:20]


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text()) if path.is_file() else {}


def remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def normalize_manifest(manifest: dict) -> dict:
    # Exclude workspace versions and local dependency paths from the dependency key.
    manifest.get("package", {}).pop("version", None)
    manifest.get("workspace", {}).get("package", {}).pop("version", None)

    def dependencies(table: dict) -> None:
        for kind in ("dependencies", "dev-dependencies", "build-dependencies"):
            for dependency in table.get(kind, {}).values():
                if isinstance(dependency, dict) and "path" in dependency:
                    dependency["path"] = ""
                    dependency.pop("version", None)

    dependencies(manifest)
    dependencies(manifest.get("workspace", {}))
    for target in manifest.get("target", {}).values():
        dependencies(target)
    return manifest


def build_environment(environment: dict[str, str]) -> dict[str, str]:
    excluded = {
        "CARGO_HOME",
        "CARGO_INSTALL_ROOT",
        "CARGO_INCREMENTAL",
        "CARGO_UNSTABLE_MTIME_ON_USE",
    }
    return {
        key: value
        for key, value in environment.items()
        if re.match(r"^(CARGO|RUST|CC|CXX|CFLAGS|CMAKE)", key)
        and key not in excluded
        and not key.startswith("RUSTUP_")
    }


def source_fingerprint(workspace: Path) -> str:
    root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=workspace, text=True
        ).strip()
    )
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=root)
    sources = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        description, name = entry.split(b"\t", 1)
        mode, object_id, stage = description.split()
        if stage != b"0":
            raise ValueError("Cannot cache a checkout with unresolved Git conflicts")
        sources[os.fsdecode(name)] = [mode.decode(), object_id.decode()]
    # Reuse indexed object IDs for unchanged paths; hash unstaged changes.
    modified = subprocess.check_output(
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-only",
            "-z",
            "--ignore-submodules=all",
        ],
        cwd=root,
    )
    for name in modified.split(b"\0"):
        if not name:
            continue
        path = root / os.fsdecode(name)
        if path.is_symlink():
            identity = ["symlink", os.readlink(path)]
        elif not path.exists():
            identity = ["missing"]
        elif not path.resolve().is_relative_to(root):
            identity = ["outside-checkout"]
        else:
            checksum = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    checksum.update(block)
            identity = [checksum.hexdigest(), stat.S_IMODE(path.stat().st_mode)]
        sources[os.fsdecode(name)] = identity
    return digest(sources)


def cache_keys(
    configuration: dict,
    compiler: str,
    cargo: str,
    manifests: list,
    lock: dict,
    cargo_config: list,
    environment: dict[str, str],
    source: str | None = None,
) -> tuple[str, list[str]]:
    scope = {
        "compiler": compiler,
        "cargo": cargo,
        "environment": build_environment(environment),
        "config": cargo_config,
        "job": environment.get("GITHUB_JOB", "") if configuration["add_job"] else "",
        "key": configuration["key"],
        "profiles": configuration["profiles"],
        "workspace_crates": configuration["workspace_crates"],
        "binaries": configuration["cache_bin"],
    }
    if configuration["workspace_crates"]:
        scope["input_schema"] = 2
    dependencies = {
        "manifests": manifests,
        "packages": [
            package for package in lock.get("package", []) if "source" in package
        ],
    }
    prefix = (
        "-".join(
            (
                configuration["prefix"],
                "native-v1",
                environment["RUNNER_OS"],
                environment["RUNNER_ARCH"],
                digest(scope),
            )
        )
        + "-"
    )
    dependency_key = prefix + digest(dependencies)
    if configuration["workspace_crates"]:
        if source is None:
            raise ValueError("Workspace caches require a source fingerprint")
        # Within each cache scope, try matching dependency keys before older ones.
        return dependency_key + "-" + source, [
            dependency_key + "-",
            dependency_key,
            prefix,
        ]
    return dependency_key, [prefix]


def prepare(configuration_path: Path) -> None:
    def value(name: str) -> str:
        return os.environ["INPUT_" + name.upper()]

    workspace = Path(value("workspace")).resolve()
    cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")).resolve()
    target = (workspace / value("target-directory")).resolve()
    profiles = sorted(
        {line.strip() for line in value("profile").splitlines() if line.strip()}
    )
    if not profiles:
        raise ValueError("At least one build profile is required")
    for profile in profiles:
        if not (target / profile).resolve().is_relative_to(target):
            raise ValueError("Build profiles must be inside the target directory")
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"],
            cwd=workspace,
            text=True,
        )
    )
    workspace_root = Path(metadata["workspace_root"])
    manifest_paths = sorted(
        {workspace_root / "Cargo.toml"}
        | {Path(package["manifest_path"]) for package in metadata["packages"]}
    )
    manifests = [normalize_manifest(read_toml(path)) for path in manifest_paths]
    lock = read_toml(workspace_root / "Cargo.lock")
    if not lock:
        raise ValueError("A current Cargo.lock is required")
    configs = []
    for parent in (workspace, *workspace.parents):
        for name in ("config", "config.toml"):
            path = parent / ".cargo" / name
            if path.is_file():
                configs.append(read_toml(path))
    for name in ("config", "config.toml"):
        path = cargo_home / name
        if path.is_file():
            configs.append(read_toml(path))
    # rustc resolves the workspace's selected toolchain; unused installations are irrelevant.
    compiler = subprocess.check_output(
        [os.environ.get("RUSTC", "rustc"), "-vV"], cwd=workspace, text=True
    ).strip()
    cargo = subprocess.check_output(
        ["cargo", "--version"], cwd=workspace, text=True
    ).strip()
    stage = Path(os.environ["RUNNER_TEMP"]) / (
        "rust-cache-binaries-" + digest(str(workspace))
    )
    remove(stage)
    stage.mkdir()
    bin_dir = cargo_home / "bin"
    configuration = {
        "workspace": str(workspace),
        "cargo_home": str(cargo_home),
        "target": str(target),
        "profiles": profiles,
        "prefix": value("prefix-key"),
        "key": value("key"),
        "add_job": value("add-job-id-key") == "true",
        "cache_bin": value("cache-bin") == "true",
        "workspace_crates": value("cache-workspace-crates") == "true",
        "binaries": str(stage),
        "initial_bins": sorted(path.name for path in bin_dir.iterdir())
        if bin_dir.is_dir()
        else [],
        "lock": str(workspace_root / "Cargo.lock"),
    }
    source = (
        source_fingerprint(workspace) if configuration["workspace_crates"] else None
    )
    key, restore_keys = cache_keys(
        configuration,
        compiler,
        cargo,
        manifests,
        lock,
        configs,
        dict(os.environ),
        source,
    )
    paths = [
        str(cargo_home / "registry"),
        str(cargo_home / "git"),
        str(target),
    ]
    if configuration["cache_bin"]:
        paths.append(str(stage))
    if configuration["workspace_crates"]:
        paths.append(value("directory"))
    configuration_path.write_text(json.dumps(configuration))
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"key={key}\nrestore-key<<RUST_CACHE_RESTORE_KEYS\n")
        output.write("\n".join(restore_keys) + "\nRUST_CACHE_RESTORE_KEYS\n")
        output.write("paths<<RUST_CACHE_PATHS\n")
        output.write("\n".join(paths) + "\nRUST_CACHE_PATHS\n")
    print(f"Active compiler: {compiler.splitlines()[0]}")
    print(f"Rust cache key: {key}")


def valid_bin(name: str) -> bool:
    return (
        bool(name)
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
        and ":" not in name
        and "\0" not in name
    )


def write_installs(cargo_home: Path, installs: dict, details: dict) -> None:
    cargo_home.mkdir(parents=True, exist_ok=True)
    lines = ["[v1]"] + [
        f"{json.dumps(key, ensure_ascii=False)} = {json.dumps(value, ensure_ascii=False)}"
        for key, value in sorted(installs.items())
    ]
    (cargo_home / ".crates.toml").write_text("\n".join(lines) + "\n")
    (cargo_home / ".crates2.json").write_text(json.dumps({"installs": details}))


def installed(cargo_home: Path) -> tuple[dict, dict]:
    installs = read_toml(cargo_home / ".crates.toml").get("v1", {})
    detail_path = cargo_home / ".crates2.json"
    details = (
        json.loads(detail_path.read_text()).get("installs", {})
        if detail_path.is_file()
        else {}
    )
    return installs, details


def restore_binaries(configuration: dict) -> None:
    if not configuration["cache_bin"]:
        return
    stage = Path(configuration["binaries"])
    cargo_home = Path(configuration["cargo_home"])
    cached, cached_details = installed(stage)
    if not cached:
        return
    current, details = installed(cargo_home)
    bin_dir = cargo_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for package, binaries in cached.items():
        restored = []
        for name in binaries:
            if not valid_bin(name):
                raise ValueError(f"Invalid Cargo binary name: {name!r}")
            source, destination = stage / "bin" / name, bin_dir / name
            if (
                source.is_file()
                and not source.is_symlink()
                and not destination.exists()
                and not destination.is_symlink()
            ):
                shutil.copy2(source, destination)
                restored.append(name)
        if restored:
            current[package] = sorted(set(current.get(package, [])) | set(restored))
            if package in cached_details:
                details[package] = {**cached_details[package], "bins": current[package]}
    write_installs(cargo_home, current, details)


def stage_binaries(configuration: dict) -> None:
    if not configuration["cache_bin"]:
        return
    cargo_home, stage = (
        Path(configuration["cargo_home"]),
        Path(configuration["binaries"]),
    )
    remove(stage)
    (stage / "bin").mkdir(parents=True)
    initial = set(configuration["initial_bins"])
    current, details = installed(cargo_home)
    saved, saved_details = {}, {}
    for package, binaries in current.items():
        selected = []
        for name in binaries:
            if not valid_bin(name):
                raise ValueError(f"Invalid Cargo binary name: {name!r}")
            source = cargo_home / "bin" / name
            if name not in initial and source.is_file() and not source.is_symlink():
                shutil.copy2(source, stage / "bin" / name)
                selected.append(name)
        if selected:
            saved[package] = selected
            if package in details:
                saved_details[package] = {**details[package], "bins": selected}
    write_installs(stage, saved, saved_details)


def clean(configuration: dict) -> None:
    cargo_home = Path(configuration["cargo_home"])
    packages = read_toml(Path(configuration["lock"])).get("package", [])
    registry_packages = {
        f"{package['name']}-{package['version']}"
        for package in packages
        if package.get("source", "").startswith("registry+")
    }
    # Keep extracted sources for workspace caches and `-sys` dependencies:
    # build scripts can depend on source mtimes.
    source_packages = (
        registry_packages
        if configuration["workspace_crates"]
        else {
            f"{package['name']}-{package['version']}"
            for package in packages
            if package["name"].endswith("-sys")
            and package.get("source", "").startswith("registry+")
        }
    )
    for kind, keep in (("cache", registry_packages), ("src", source_packages)):
        directory = cargo_home / "registry" / kind
        if directory.is_dir():
            for registry in directory.iterdir():
                if registry.is_dir() and not registry.is_symlink():
                    for package in registry.iterdir():
                        name = (
                            package.name.removesuffix(".crate")
                            if kind == "cache"
                            else package.name
                        )
                        if name not in keep:
                            remove(package)
    target = Path(configuration["target"])
    profiles = {path.parent for path in target.rglob(".fingerprint") if path.is_dir()}
    ancestors = {
        parent
        for profile in profiles
        for parent in profile.parents
        if parent.is_relative_to(target)
    }

    def clean_target(directory: Path) -> None:
        if directory in profiles:
            keep = {".fingerprint", "deps", "build"}
            for artifact in directory.iterdir():
                if artifact.name not in keep:
                    remove(artifact)
        elif directory.is_dir():
            for artifact in directory.iterdir():
                if not artifact.is_symlink() and artifact in profiles | ancestors:
                    clean_target(artifact)
                elif artifact.name not in {".rustc_info.json", "CACHEDIR.TAG"}:
                    remove(artifact)

    clean_target(target)
    stage_binaries(configuration)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "restore", "save"))
    parser.add_argument("configuration", type=Path)
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.configuration)
    else:
        configuration = json.loads(args.configuration.read_text())
        (restore_binaries if args.operation == "restore" else clean)(configuration)


if __name__ == "__main__":
    main()
