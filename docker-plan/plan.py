"""Plan Astral Docker builds without granting permission to publish them."""

import json
import os
import re
from pathlib import Path


def main():
    name = os.environ["NAME"]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise SystemExit(f"Invalid Astral project name: {name!r}")

    repository = os.environ["GITHUB_REPOSITORY"]
    primary_repository = f"astral-sh/{name}"
    if repository not in {primary_repository, f"{primary_repository}-dev"}:
        raise SystemExit(f"No Astral Docker project configured for {repository}")

    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    head_repository = event.get("pull_request", {}).get("head", {}).get("repo") or {}
    same_repository_pr = (
        os.environ["GITHUB_EVENT_NAME"] == "pull_request"
        and head_repository.get("full_name") == repository
    )
    primary_repository_pr = repository == primary_repository and same_repository_pr
    release_plan = os.environ["PLAN"]
    push_dev = os.environ["PUSH_DEV"] == "true"

    version = ""
    if push_dev:
        if not same_repository_pr or release_plan:
            raise SystemExit(
                "Development publication requires a same-repository Astral pull request "
                "without a release plan"
            )
        mode = "development"
        save = True
        publish = True
    elif release_plan:
        plan = json.loads(release_plan)
        implicit = plan["announcement_tag_is_implicit"]
        if not isinstance(implicit, bool):
            raise SystemExit(
                "The release plan must declare whether its tag is implicit"
            )
        mode = "dry-run" if implicit else "release"
        save = True
        publish = not implicit
        if publish:
            version = plan["announcement_tag"]
            if not isinstance(version, str) or not re.fullmatch(
                r"[0-9][a-zA-Z0-9.!+_-]*", version
            ):
                raise SystemExit("The release plan must contain a release version")
    else:
        mode = "dry-run"
        save = False
        publish = False

    login = mode == "release" or primary_repository_pr
    project = (
        os.environ["PRODUCTION_PROJECT"]
        if repository == primary_repository and release_plan and not push_dev
        else os.environ["DEVELOPMENT_PROJECT"]
    )
    if not re.fullmatch(r"[a-zA-Z0-9]+", project):
        raise SystemExit("A Depot project ID is required")

    images = [f"ghcr.io/astral-sh/{name}{'-dev' if push_dev else ''}"]
    if os.environ["DOCKERHUB"] == "true" and not push_dev:
        images.append(f"docker.io/astral/{name}")
    mappings = [
        mapping
        for line in os.environ["IMAGE_MAPPINGS"].splitlines()
        if (mapping := line.strip()) and (login or not mapping.startswith("dhi.io/"))
    ]

    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        print(f"depot-project-id={project}", file=output)
        print(f"ghcr-image={images[0]}", file=output)
        print("images<<DOCKER_IMAGES", *images, "DOCKER_IMAGES", sep="\n", file=output)
        print(f"login={str(login).lower()}", file=output)
        print(f"publish={str(publish).lower()}", file=output)
        print(f"mode={mode}", file=output)
        print(f"save={str(save).lower()}", file=output)
        print(f"version={version}", file=output)
        print(f"matrix={json.dumps({'image-mapping': mappings})}", file=output)


if __name__ == "__main__":
    main()
