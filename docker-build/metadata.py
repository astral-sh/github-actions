"""Check the project release version and generate Astral Docker tag rules."""

import os
import re
import tomllib
from pathlib import Path


def main():
    mode = os.environ["MODE"]
    version = os.environ["VERSION"]
    aliases = os.environ["ALIASES"].splitlines()
    if mode not in {"release", "development", "dry-run"}:
        raise SystemExit(f"Unknown Docker build mode: {mode!r}")
    if any(
        not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*", alias) for alias in aliases
    ):
        raise SystemExit("Invalid Docker image alias")

    if mode == "release":
        if not re.fullmatch(r"[0-9][a-zA-Z0-9.!+_-]*", version):
            raise SystemExit("Release builds require a release version")
        # Variants use the version checked by their base-image build and do not
        # need a source checkout.
        if not aliases:
            pyproject = Path("pyproject.toml")
            with pyproject.open("rb") as source:
                project_version = tomllib.load(source)["project"]["version"]
            if version != project_version:
                raise SystemExit(
                    f"The release version {version!r} does not match "
                    f"project.version {project_version!r} in {pyproject}"
                )
            print(f"Releasing {version}")

    tags = []
    for alias in aliases or [""]:
        suffix = f",suffix=-{alias}" if alias else ""
        if mode == "release":
            # The full version and first alias determine the OCI version label.
            tags.append(
                f"type=pep440,pattern={{{{ version }}}}{suffix},value={version}"
            )
            tags.append(
                f"type=pep440,pattern={{{{ major }}}}.{{{{ minor }}}}{suffix},value={version}"
            )
        elif mode == "development":
            tags.append(f"type=sha{suffix}")

        if mode != "development":
            if alias:
                tags.append(f"type=raw,value={alias}")
            elif mode == "dry-run":
                tags.append("type=raw,value=dry-run")

    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        print("tags<<DOCKER_TAGS", *tags, "DOCKER_TAGS", sep="\n", file=output)
        print(f"flavor=latest={'false' if aliases else 'auto'}", file=output)


if __name__ == "__main__":
    main()
