"""Generate Cargo Vet policies for first-party packages in the current workspace."""

import json
import os
import subprocess
import sys
from pathlib import Path

import tomli_w


def cargo_metadata(workspace: Path, *arguments: str) -> dict:
    return json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--format-version", "1", *arguments],
            cwd=workspace,
        )
    )


def main() -> None:
    root = Path(os.environ["GITHUB_WORKSPACE"])
    workspaces = set(json.loads(os.environ["FIRST_PARTY_WORKSPACES"]))
    manifests = {
        package["manifest_path"]
        for workspace in sorted(workspaces)
        for package in cargo_metadata(root / workspace, "--no-deps")["packages"]
    }

    packages = cargo_metadata(Path.cwd(), "--all-features", "--locked")["packages"]
    names = {
        package["name"]
        for package in packages
        if package["source"] is None and package["manifest_path"] in manifests
    }
    if names:
        sys.stdout.buffer.write(b"\n")
        tomli_w.dump(
            {
                "policy": {
                    name: {
                        "audit-as-crates-io": False,
                        "criteria": "safe-to-deploy",
                        "dev-criteria": "safe-to-deploy",
                    }
                    for name in sorted(names)
                }
            },
            sys.stdout.buffer,
        )


if __name__ == "__main__":
    main()
