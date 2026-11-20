"""Submit built documentation to the central docs repository."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

REPOSITORY = "astral-sh/docs"
BASE_BRANCH = "main"
GIT_AUTH = ("-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential")


def capture(*command, cwd=None, check=True):
    return subprocess.run(
        command, cwd=cwd, check=check, stdout=subprocess.PIPE, text=True
    )


def api(method, path, *fields, check=True):
    return capture(
        "gh", "api", "--hostname", "github.com", "--method", method,
        f"repos/{REPOSITORY}/{path}", *fields, check=check,
    )


def built_site(workspace: Path, source: str) -> Path:
    path = workspace / source
    if not source or path.is_symlink():
        raise ValueError("Expected a built source directory, without a symlink")
    path = path.resolve(strict=True)
    if path == workspace or not path.is_relative_to(workspace) or not path.is_dir():
        raise ValueError("The source must be a directory under the caller's workspace")
    if any(part.lower() == ".git" for part in path.relative_to(workspace).parts):
        raise ValueError("The source must be outside Git metadata")

    has_files = False
    for entry in path.rglob("*"):
        if entry.is_symlink() or entry.name.lower() == ".git":
            raise ValueError("The built site must contain regular files and directories")
        if entry.is_file():
            has_files = True
        elif not entry.is_dir():
            raise ValueError("The built site must contain regular files and directories")
    if not has_files:
        raise ValueError("The built site is empty")
    return path


def stage_site(checkout: Path, source: Path, destination: str) -> None:
    target = checkout / destination
    if target.parent.is_symlink() or target.is_symlink():
        raise ValueError("The destination and its parent must not be symlinks")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)
    capture("git", "add", "--all", "--force", "--", destination, cwd=checkout)


def push_update(checkout: Path, destination: str, branch: str, expected: str) -> str:
    """Reuse an identical proposal, otherwise update only the branch we observed."""
    ref = f"refs/heads/{branch}"
    if expected:
        capture("git", *GIT_AUTH, "fetch", "--depth=1", "--no-tags", "origin", ref, cwd=checkout)
        fetched = capture("git", "rev-parse", "FETCH_HEAD", cwd=checkout).stdout.strip()
        if fetched != expected:
            raise ValueError("The publication branch changed during this run. Retry the update.")
        base = capture("git", "rev-parse", "HEAD", cwd=checkout).stdout.strip()
        tree = capture("git", "write-tree", cwd=checkout).stdout.strip()
        commit = capture("git", "cat-file", "commit", fetched, cwd=checkout).stdout
        if commit.startswith(f"tree {tree}\nparent {base}\n"):
            return fetched

    capture(
        "git",
        "-c", "user.name=astral-releases-bot[bot]",
        "-c", "user.email=328004183+astral-releases-bot[bot]@users.noreply.github.com",
        "commit", "-m", f"Update documentation at {destination}",
        cwd=checkout,
    )
    capture(
        "git", *GIT_AUTH, "push", f"--force-with-lease={ref}:{expected}",
        "origin", f"HEAD:{ref}", cwd=checkout,
    )
    return capture("git", "rev-parse", "HEAD", cwd=checkout).stdout.strip()


def open_pull_request(branch: str, title: str, body: str) -> dict:
    def find():
        result = api(
            "GET", "pulls", "-f", "state=open", "-f", f"base={BASE_BRANCH}",
            "-f", f"head=astral-sh:{branch}",
        )
        return next(
            (
                pr for pr in json.loads(result.stdout)
                if (pr["head"]["repo"] or {}).get("full_name") == REPOSITORY
                and pr["head"]["ref"] == branch
            ),
            None,
        )

    pull_request = find()
    if pull_request is None:
        result = api(
            "POST", "pulls", "-f", f"base={BASE_BRANCH}", "-f", f"head={branch}",
            "-f", f"title={title}", "-f", f"body={body}", check=False,
        )
        if result.returncode == 0:
            pull_request = json.loads(result.stdout)
        else:
            # Another run may have created the PR after we checked, or the request
            # may have succeeded before the client lost its response.
            pull_request = find()
            if pull_request is None:
                result.check_returncode()

    api("POST", f"issues/{pull_request['number']}/labels", "-f", "labels[]=documentation")
    return pull_request


def merge_exact(number: int, commit: str) -> None:
    # GitHub computes mergeability asynchronously after a PR is created or updated.
    for attempt in range(6):
        pull_request = json.loads(api("GET", f"pulls/{number}").stdout)
        # The API can still report the previous head immediately after a push.
        if pull_request["head"]["sha"] == commit:
            if pull_request["merged"]:
                return
            if pull_request["mergeable"] is not None:
                capture(
                    "gh", "pr", "merge", str(number), "--repo", f"github.com/{REPOSITORY}",
                    "--squash", "--admin", "--match-head-commit", commit,
                )
                return
        if attempt < 5:
            time.sleep(2)
    raise ValueError("GitHub did not report mergeability for the published commit. Retry the update.")


def publish(checkout: Path, source: Path, destination: str, branch: str, merge_policy: str) -> str:
    capture(
        "git", *GIT_AUTH, "clone", "--depth=1", "--no-tags", "--no-recurse-submodules",
        "--single-branch", "--branch", BASE_BRANCH,
        f"https://github.com/{REPOSITORY}.git", str(checkout),
    )
    ref = f"refs/heads/{branch}"
    remote = capture("git", *GIT_AUTH, "ls-remote", "--refs", "origin", ref, cwd=checkout)
    expected = remote.stdout.partition("\t")[0]
    stage_site(checkout, source, destination)

    status = capture("git", "diff", "--cached", "--quiet", cwd=checkout, check=False)
    if status.returncode == 0:
        print("The documentation is already up to date.")
        return ""
    if status.returncode != 1:
        status.check_returncode()

    commit = push_update(checkout, destination, branch, expected)
    pull_request = open_pull_request(branch, os.environ["DOCS_PR_TITLE"], os.environ["DOCS_PR_BODY"])
    url = pull_request["html_url"]
    if merge_policy == "squash-admin":
        merge_exact(pull_request["number"], commit)
    print(url)
    return url


def main() -> None:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    destination = os.environ["DOCS_DESTINATION"]
    publication_key = os.environ["DOCS_PUBLICATION_KEY"]
    merge_policy = os.environ["DOCS_MERGE_POLICY"]
    if not re.fullmatch(r"site/[a-z0-9][a-z0-9-]*", destination):
        raise ValueError("Expected a destination of the form site/<project>")
    required = (publication_key, os.environ["DOCS_PR_TITLE"], os.environ["GH_TOKEN"])
    if not all(value.strip() for value in required):
        raise ValueError("A publication key, pull request title, and scoped token are required")
    if merge_policy not in {"review", "squash-admin"}:
        raise ValueError("Expected a merge policy of review or squash-admin")

    source = built_site(workspace, os.environ["DOCS_SOURCE_DIRECTORY"])
    update_id = hashlib.sha256(publication_key.encode()).hexdigest()[:20]
    project = destination.removeprefix("site/")
    # The destination ruleset protects branches matching update-docs-*.
    branch = f"update-docs-{project}-{update_id}"
    with tempfile.TemporaryDirectory(prefix="publish-docs-", dir=os.environ["RUNNER_TEMP"]) as directory:
        url = publish(Path(directory) / "docs", source, destination, branch, merge_policy)

    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        print(f"changed={str(bool(url)).lower()}", file=output)
        print(f"pull-request-url={url}", file=output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
