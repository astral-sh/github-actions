"""Exercise the action against a local versions repository and a GitHub CLI stub."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ACTION = Path(__file__).resolve().parent
PR_URL = "https://github.com/astral-sh/versions/pull/1"

GH_STUB = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

command, subcommand, *arguments = sys.argv[1:]
assert command == "pr" and os.environ["GH_TOKEN"] == "test-token"

phase = Path(os.environ["TEST_STATE"])
state = json.loads(phase.read_text())
url = "https://github.com/astral-sh/versions/pull/1"
branch = os.environ["BRANCH"]
head = subprocess.check_output(
    ["git", "--git-dir", os.environ["TEST_REMOTE"], "rev-parse", branch],
    text=True,
).strip()
if subcommand == "list":
    if state["has_pr"]:
        print(url)
elif subcommand == "create":
    assert arguments[arguments.index("--head") + 1] == branch
    assert not state["has_pr"]
    state["has_pr"] = True
    print(url)
elif subcommand == "view":
    state["reads"] += 1
    if state["reads"] == 1:
        print("0" * 40, "MERGEABLE", "OPEN", sep="\t")
    elif state["reads"] == 2:
        print(head, "UNKNOWN", "OPEN", sep="\t")
    else:
        print(head, "MERGEABLE", "OPEN", sep="\t")
elif subcommand == "merge":
    assert arguments[-2:] == ["--match-head-commit", head]
    state["merged"].append(head)
else:
    raise SystemExit(f"Unexpected command: {subcommand}")
phase.write_text(json.dumps(state))
"""


def metadata(version):
    return json.dumps({
        "version": version,
        "date": "2026-11-01T00:00:00Z",
        "artifacts": [{
            "platform": "x86_64-unknown-linux-gnu",
            "variant": "default",
            "url": "https://example.invalid/archive.tar.gz",
            "archive_format": "tar.gz",
            "sha256": "a" * 64,
        }],
    }, separators=(",", ":")) + "\n"


class PublishReleaseMetadataTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.input = self.root / "metadata.ndjson"
        self.output = self.root / "output"
        self.state = self.root / "prs.json"
        self.state.write_text('{"has_pr": false, "reads": 0, "merged": []}')
        self.input.write_text(metadata("1.1.0"))

        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(GH_STUB)
        gh.chmod(0o755)
        self.env = os.environ | {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.remote.as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/astral-sh/versions.git",
            "GIT_AUTHOR_NAME": "Release metadata test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Release metadata test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "RUNNER_TEMP": str(self.root),
            "GITHUB_OUTPUT": str(self.output),
            "PROJECT": "uv",
            "RELEASE": "1.1.0",
            "METADATA_FILE": str(self.input),
            "MERGE_MODE": "review",
            "GH_TOKEN": "test-token",
            "TEST_STATE": str(self.state),
            "TEST_REMOTE": str(self.remote),
        }
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.git("init", "--initial-branch=main", str(self.seed))
        versions = self.seed / "v1"
        versions.mkdir()
        (versions / "uv.ndjson").write_text(metadata("1.0.0"))
        (versions / "ruff.ndjson").write_text(metadata("2.0.0"))
        self.git("-C", str(self.seed), "add", "v1")
        self.git("-C", str(self.seed), "commit", "-m", "Seed versions")
        self.git("-C", str(self.seed), "push", str(self.remote), "main")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True, env=self.env
        ).stdout.strip()

    def run_script(self, script, expected=0, **env):
        self.output.write_text("")
        result = subprocess.run(
            ["bash", str(ACTION / script)],
            env=self.env | env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def publish(self, prepared, **env):
        return self.run_script(
            "publish.sh",
            STAGING_DIR=prepared["staging-dir"],
            BRANCH=prepared["branch"],
            EXPECTED_HEAD=prepared["expected-head"],
            **env,
        )

    def test_protected_branch_and_retry_then_exact_head_merge(self):
        first = self.run_script("prepare.sh")
        self.assertEqual(first["changed"], "true")
        branch = first["branch"]
        self.assertRegex(branch, r"^update-versions-uv-[a-f0-9]{20}$")
        self.assertEqual(self.publish(first), {"pull-request-url": PR_URL})
        head = self.git("--git-dir", str(self.remote), "rev-parse", branch)
        self.assertEqual(
            self.git("--git-dir", str(self.remote), "diff", "--name-only", "main", head),
            "v1/uv.ndjson",
        )
        data = self.git("--git-dir", str(self.remote), "show", f"{head}:v1/uv.ndjson")
        self.assertEqual({json.loads(line)["version"] for line in data.splitlines()}, {"1.0.0", "1.1.0"})
        self.assertEqual(json.loads(self.state.read_text())["merged"], [])

        retry = self.run_script("prepare.sh", MERGE_MODE="admin-squash")
        self.assertEqual(retry["expected-head"], head)
        self.assertEqual(self.publish(retry, MERGE_MODE="admin-squash"), {"pull-request-url": PR_URL})
        state = json.loads(self.state.read_text())
        self.assertEqual(state["reads"], 3)
        self.assertEqual(state["merged"], [head])

    def test_ref_created_after_prepare_is_preserved(self):
        prepared = self.run_script("prepare.sh")
        branch = prepared["branch"]
        self.git("-C", str(self.seed), "push", str(self.remote), f"HEAD:refs/heads/{branch}")

        self.publish(prepared, expected=1)

        head = self.git("--git-dir", str(self.remote), "rev-parse", branch)
        self.assertEqual(head, self.git("--git-dir", str(self.remote), "rev-parse", "main"))
        self.assertFalse(json.loads(self.state.read_text())["has_pr"])

    def test_already_published_and_invalid_metadata(self):
        self.input.write_text(metadata("1.0.0"))
        self.assertEqual(self.run_script("prepare.sh"), {"changed": "false"})
        self.input.write_text('{"version":"1.1.0"}\n')
        self.assertEqual(self.run_script("prepare.sh", expected=1), {})
        self.assertEqual(list(self.root.glob("versions-update.*")), [])
