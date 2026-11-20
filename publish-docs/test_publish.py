"""Exercise publication against a local bare Git repository and a GitHub CLI stub."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import publish

GH_STUB = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
state_path = Path(os.environ["TEST_PR_STATE"])
state = json.loads(state_path.read_text())
if args[:3] == ["api", "--hostname", "github.com"]:
    method, route = args[4:6]
    fields = dict(field.split("=", 1) for field in args[7::2])
    if route == "repos/astral-sh/docs/pulls":
        branch = fields["head"].removeprefix("astral-sh:")
        if method == "GET":
            pr = state["pulls"].get(branch)
            print(json.dumps([pr] if pr else []))
        else:
            number = len(state["pulls"]) + 1
            pr = {
                "number": number,
                "head": {"repo": {"full_name": "astral-sh/docs"}, "ref": branch},
                "html_url": f"https://github.com/astral-sh/docs/pull/{number}",
                "title": fields["title"], "body": fields["body"],
            }
            if branch in state["pulls"]:
                raise SystemExit("Already exists")
            state["pulls"][branch] = pr
            print(json.dumps(pr))
    elif route.startswith("repos/astral-sh/docs/pulls/") and method == "GET":
        number = int(route.split("/")[-1])
        pr = next(pr for pr in state["pulls"].values() if pr["number"] == number)
        sha = subprocess.check_output(
            ["git", "--git-dir", os.environ["TEST_REMOTE"], "rev-parse", pr["head"]["ref"]],
            text=True,
        ).strip()
        if os.environ.get("TEST_STALE_HEAD") and not state.get("reported_stale_head"):
            state["reported_stale_head"] = True
            sha = "0" * 40
        print(json.dumps({"head": {"sha": sha}, "merged": False, "mergeable": True}))
    elif route.startswith("repos/astral-sh/docs/issues/") and method == "POST":
        state["labels"][route.split("/")[4]] = fields["labels[]"]
    else:
        raise SystemExit(f"Unexpected request: {args}")
elif args[:2] == ["pr", "merge"]:
    state["merges"].append(args[2:])
else:
    raise SystemExit(f"Unexpected command: {args}")
state_path.write_text(json.dumps(state))
"""


class PublishDocsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.remote = root / "remote.git"
        self.checkout = root / "seed"
        self.workspace = root / "workspace"
        self.output = root / "output"
        self.state_path = root / "prs.json"
        self.source = self.workspace / "built"
        self.source.mkdir(parents=True)
        (self.source / "index.html").write_text("new site")
        self.state_path.write_text('{"pulls": {}, "labels": {}, "merges": []}')
        bin_dir = root / "bin"
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
            "GIT_CONFIG_VALUE_0": "https://github.com/astral-sh/docs.git",
            "GIT_AUTHOR_NAME": "Doc publisher test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Doc publisher test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GITHUB_WORKSPACE": str(self.workspace),
            "GITHUB_OUTPUT": str(self.output),
            "RUNNER_TEMP": str(root),
            "GH_TOKEN": "fake",
            "DOCS_DESTINATION": "site/uv",
            "DOCS_SOURCE_DIRECTORY": "built",
            "DOCS_PUBLICATION_KEY": "release-1",
            "DOCS_PR_TITLE": "Initial title",
            "DOCS_PR_BODY": "Initial description",
            "DOCS_MERGE_POLICY": "review",
            "TEST_PR_STATE": str(self.state_path),
            "TEST_REMOTE": str(self.remote),
        }
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.git("init", "--initial-branch=main", str(self.checkout))
        for directory, filename, content in [
            ("site/uv", "old.html", "old site"),
            ("site/ty", "index.html", "ty site"),
        ]:
            project = self.checkout / directory
            project.mkdir(parents=True)
            (project / filename).write_text(content)
        self.git("-C", str(self.checkout), "add", ".")
        self.git("-C", str(self.checkout), "commit", "-m", "Seed the docs repository")
        self.git("-C", str(self.checkout), "push", str(self.remote), "main")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], text=True, capture_output=True, check=True, env=self.env
        ).stdout.strip()

    def run_action(self, expected=0, **overrides):
        self.output.write_text("")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("publish.py"))],
            env=self.env | overrides, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return self.output.read_text()

    def branch(self, project="uv", key="release-1"):
        update_id = hashlib.sha256(key.encode()).hexdigest()[:20]
        return f"update-docs-{project}-{update_id}"

    def test_replaces_only_the_target_subtree_and_reuses_the_pull_request(self):
        branch = self.branch()
        output = self.run_action()
        commit = self.git("--git-dir", str(self.remote), "rev-parse", branch)
        self.assertIn("changed=true", output)
        self.assertIn("pull-request-url=https://github.com/astral-sh/docs/pull/1", output)
        files = self.git("--git-dir", str(self.remote), "ls-tree", "-r", "--name-only", branch)
        self.assertEqual(files, "site/ty/index.html\nsite/uv/index.html")
        self.assertEqual(output, self.run_action())
        self.assertEqual(commit, self.git("--git-dir", str(self.remote), "rev-parse", branch))

        (self.source / "index.html").write_text("updated site")
        self.assertEqual(output, self.run_action(
            DOCS_PR_TITLE="New title", DOCS_MERGE_POLICY="squash-admin",
        ))
        updated_commit = self.git("--git-dir", str(self.remote), "rev-parse", branch)
        self.assertNotEqual(commit, updated_commit)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["pulls"][branch]["title"], "Initial title")
        self.assertEqual(state["labels"], {"1": "documentation"})
        self.assertEqual(state["merges"], [[
            "1", "--repo", "github.com/astral-sh/docs", "--squash",
            "--admin", "--match-head-commit", updated_commit,
        ]])

    def test_admin_merge_waits_for_the_published_head(self):
        self.run_action(DOCS_MERGE_POLICY="squash-admin", TEST_STALE_HEAD="1")

        state = json.loads(self.state_path.read_text())
        head = self.git("--git-dir", str(self.remote), "rev-parse", self.branch())
        self.assertTrue(state["reported_stale_head"])
        self.assertEqual(len(state["merges"]), 1)
        self.assertEqual(state["merges"][0][-2:], ["--match-head-commit", head])

    def test_sites_and_publication_keys_get_separate_branches(self):
        self.run_action()
        self.run_action(DOCS_DESTINATION="site/ty")
        self.run_action(DOCS_PUBLICATION_KEY="preview")
        state = json.loads(self.state_path.read_text())
        self.assertEqual(
            set(state["pulls"]), {self.branch(), self.branch("ty"), self.branch(key="preview")}
        )
        self.assertEqual(state["merges"], [])

    def test_no_change_and_invalid_destinations_do_not_publish(self):
        index = self.source / "index.html"
        index.rename(self.source / "old.html")
        (self.source / "old.html").write_text("old site")
        self.assertEqual(self.run_action(), "changed=false\npull-request-url=\n")
        self.run_action(expected=1, DOCS_DESTINATION="site")
        self.run_action(expected=1, DOCS_DESTINATION="site/../ty")
        (self.workspace / ".git").mkdir()
        (self.workspace / ".git" / "config").write_text("Git config")
        self.run_action(expected=1, DOCS_SOURCE_DIRECTORY=".git")
        (self.source / "link").symlink_to(self.checkout)
        self.run_action(expected=1)
        self.assertEqual(json.loads(self.state_path.read_text())["pulls"], {})

    def test_update_rejects_a_changed_remote_branch(self):
        self.run_action()
        branch = self.branch()
        expected = self.git("--git-dir", str(self.remote), "rev-parse", branch)
        self.git("-C", str(self.checkout), "commit", "--allow-empty", "-m", "Concurrent update")
        self.git("-C", str(self.checkout), "push", "--force", str(self.remote), f"HEAD:refs/heads/{branch}")
        self.git("-C", str(self.checkout), "remote", "add", "origin", str(self.remote))
        with self.assertRaisesRegex(ValueError, "publication branch changed"):
            publish.push_update(self.checkout, "site/uv", branch, expected)
