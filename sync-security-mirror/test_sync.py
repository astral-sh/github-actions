import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync.sh").resolve()
MAIN = "refs/heads/main"


class SyncSecurityMirrorTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.directory = Path(temporary_directory.name)
        self.source = self.directory / "source"
        self.destination = self.directory / "destination.git"
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }

        self.git("init", "--quiet", "--initial-branch=main", str(self.source))
        self.git("-C", str(self.source), "commit", "--quiet", "--allow-empty", "-m", "Base")
        self.base = self.git("-C", str(self.source), "rev-parse", "HEAD")
        self.git("-C", str(self.source), "commit", "--quiet", "--allow-empty", "-m", "Public")
        self.public_commit = self.git("-C", str(self.source), "rev-parse", "HEAD")
        self.git("clone", "--quiet", "--bare", str(self.source), str(self.destination))
        self.git("-C", str(self.destination), "update-ref", MAIN, self.base)

        # Route the action's fixed GitHub URLs to local Git fixtures. Check that
        # the mirror token is visible only to destination remote commands.
        git_shim = self.directory / "git"
        git_shim.write_text(
            """#!/usr/bin/env python3
import os
import sys

arguments = sys.argv[1:]
for index, argument in enumerate(arguments):
    if argument == "https://github.com/example/source.git":
        assert "http.extraHeader=Authorization:" in arguments
        assert "GH_TOKEN" not in os.environ
        assert "DESTINATION_TOKEN" not in os.environ
        arguments[index] = os.environ["TEST_SOURCE_URL"]
    elif argument == "https://github.com/example/mirror.git":
        assert os.environ["GH_TOKEN"] == "test-installation-token"
        assert "DESTINATION_TOKEN" not in os.environ
        if "push" in arguments and "TEST_RACE_SHA" in os.environ:
            import subprocess

            git = [os.environ["TEST_GIT"], "-C", os.environ["TEST_DESTINATION"]]
            race_sha = os.environ["TEST_RACE_SHA"]
            update = ["refs/heads/main", race_sha] if race_sha else ["-d", "refs/heads/main"]
            subprocess.run([*git, "update-ref", *update], check=True)
        arguments[index] = os.environ["TEST_DESTINATION_URL"]

git = os.environ["TEST_GIT"]
os.execv(git, [git, *arguments])
"""
        )
        git_shim.chmod(0o755)
        self.action_env = {
            **self.env,
            "PATH": os.pathsep.join((str(self.directory), os.environ["PATH"])),
            "RUNNER_TEMP": str(self.directory),
            "TEST_GIT": shutil.which("git"),
            "TEST_SOURCE_URL": self.source.as_uri(),
            "TEST_DESTINATION": str(self.destination),
            "TEST_DESTINATION_URL": self.destination.as_uri(),
            "SOURCE_REPOSITORY": "example/source",
            "DESTINATION_REPOSITORY": "example/mirror",
            "DESTINATION_TOKEN": "test-installation-token",
            "GH_TOKEN": "inherited-token",
        }

    def git(self, *args):
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True, env=self.env
        ).stdout.strip()

    def sync(self, source_sha):
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**self.action_env, "SOURCE_SHA": source_sha},
            capture_output=True,
            text=True,
        )
        self.assertEqual(list(self.directory.glob("security-mirror.*")), [])
        return result

    def mirror_main(self):
        return self.git("-C", str(self.destination), "rev-parse", MAIN)

    def test_fast_forward_and_retry(self):
        result = self.sync(self.public_commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mirror_main(), self.public_commit)

        result = self.sync(self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already contains", result.stdout)
        self.assertEqual(self.mirror_main(), self.public_commit)

    def test_rejects_commit_outside_public_main(self):
        self.git("-C", str(self.source), "switch", "-c", "experimental", self.base)
        self.git("-C", str(self.source), "commit", "--quiet", "--allow-empty", "-m", "Other")
        other_commit = self.git("-C", str(self.source), "rev-parse", "HEAD")

        result = self.sync(other_commit)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requested commit is not on public main", result.stderr)
        self.assertEqual(self.mirror_main(), self.base)

    def test_refuses_to_push_over_private_history(self):
        tree = self.git("-C", str(self.destination), "rev-parse", f"{self.base}^{{tree}}")
        private_commit = self.git(
            "-C", str(self.destination), "commit-tree", tree, "-p", self.base, "-m", "Private"
        )
        self.git("-C", str(self.destination), "update-ref", MAIN, private_commit)

        result = self.sync(self.public_commit)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Destination main is not on public main", result.stderr)
        self.assertNotIn(private_commit, result.stdout + result.stderr)
        self.assertEqual(self.mirror_main(), private_commit)

    def test_refuses_to_rewind_if_mirror_advances_during_sync(self):
        self.git("-C", str(self.source), "commit", "--quiet", "--allow-empty", "-m", "Later")
        later_commit = self.git("-C", str(self.source), "rev-parse", "HEAD")
        self.git("-C", str(self.source), "push", "--quiet", str(self.destination), "HEAD:refs/heads/later")
        self.action_env["TEST_RACE_SHA"] = later_commit

        result = self.sync(self.public_commit)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not fast-forward", result.stderr)
        self.assertEqual(self.mirror_main(), later_commit)


    def test_refuses_to_recreate_mirror_main_if_deleted_during_sync(self):
        self.action_env["TEST_RACE_SHA"] = ""

        result = self.sync(self.public_commit)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not fast-forward", result.stderr)
        self.assertEqual(self.git("-C", str(self.destination), "for-each-ref", MAIN), "")


if __name__ == "__main__":
    unittest.main()
