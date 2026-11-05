import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_MAPPINGS = "alpine:3.23,alpine3.23,alpine\ndhi.io/python:3.14,python3.14-dhi\n"


class DockerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.output = self.path / "output"
        self.event = self.path / "event.json"
        self.event.write_text(
            json.dumps(
                {"pull_request": {"head": {"repo": {"full_name": "astral-sh/uv"}}}}
            )
        )
        self.environment = dict(
            os.environ,
            GITHUB_OUTPUT=str(self.output),
            GITHUB_EVENT_PATH=str(self.event),
            GITHUB_EVENT_NAME="pull_request",
            GITHUB_REPOSITORY="astral-sh/uv",
            NAME="uv",
            PLAN="",
            PUSH_DEV="false",
            PRODUCTION_PROJECT="production",
            DEVELOPMENT_PROJECT="development",
            DOCKERHUB="true",
            IMAGE_MAPPINGS=IMAGE_MAPPINGS,
            MODE="dry-run",
            VERSION="",
            ALIASES="",
        )

    def run_script(self, script, *, success=True, **environment):
        self.output.write_text("")
        result = subprocess.run(
            [sys.executable, str(ROOT / script)],
            cwd=self.path,
            env=dict(self.environment, **environment),
            capture_output=True,
            text=True,
            check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(self.output.read_text(), "")
        return result

    def outputs(self):
        outputs = {}
        lines = iter(self.output.read_text().splitlines())
        for line in lines:
            if "<<" in line:
                name, delimiter = line.split("<<", 1)
                value = []
                for part in lines:
                    if part == delimiter:
                        break
                    value.append(part)
                outputs[name] = "\n".join(value)
            else:
                name, value = line.split("=", 1)
                outputs[name] = value
        return outputs

    def test_pull_request_does_not_save_or_publish(self):
        self.run_script("docker-plan/plan.py")
        self.assertEqual(
            self.outputs(),
            {
                "depot-project-id": "development",
                "ghcr-image": "ghcr.io/astral-sh/uv",
                "images": "ghcr.io/astral-sh/uv\ndocker.io/astral/uv",
                "login": "true",
                "publish": "false",
                "mode": "dry-run",
                "save": "false",
                "version": "",
                "matrix": json.dumps({"image-mapping": IMAGE_MAPPINGS.splitlines()}),
            },
        )

    def test_fork_pull_request_excludes_authenticated_images(self):
        self.event.write_text(
            json.dumps(
                {"pull_request": {"head": {"repo": {"full_name": "contributor/uv"}}}}
            )
        )
        self.run_script("docker-plan/plan.py")
        self.assertEqual(self.outputs()["login"], "false")
        self.assertEqual(self.outputs()["save"], "false")
        self.assertEqual(self.outputs()["publish"], "false")
        self.assertEqual(
            json.loads(self.outputs()["matrix"]),
            {"image-mapping": ["alpine:3.23,alpine3.23,alpine"]},
        )

    def test_release_selects_production_project_and_version(self):
        self.run_script(
            "docker-plan/plan.py",
            PLAN='{"announcement_tag_is_implicit": false, "announcement_tag": "1.2.3"}',
            GITHUB_EVENT_NAME="workflow_dispatch",
        )
        self.assertEqual(self.outputs()["mode"], "release")
        self.assertEqual(self.outputs()["version"], "1.2.3")
        self.assertEqual(self.outputs()["depot-project-id"], "production")
        self.assertEqual(self.outputs()["save"], "true")
        self.assertEqual(self.outputs()["publish"], "true")
        self.assertEqual(self.outputs()["login"], "true")

    def test_deleted_fork_does_not_enable_authenticated_pulls(self):
        self.event.write_text(json.dumps({"pull_request": {"head": {"repo": None}}}))
        self.run_script("docker-plan/plan.py")
        self.assertEqual(self.outputs()["login"], "false")
        self.run_script("docker-plan/plan.py", PUSH_DEV="true", success=False)

    def test_release_plan_requires_boolean_intent_and_a_safe_version(self):
        for plan in (
            {"announcement_tag_is_implicit": "false", "announcement_tag": "1.2.3"},
            {
                "announcement_tag_is_implicit": False,
                "announcement_tag": "1.2.3\nmode=development",
            },
            {"announcement_tag_is_implicit": False, "announcement_tag": ""},
        ):
            with self.subTest(plan=plan):
                self.run_script(
                    "docker-plan/plan.py", PLAN=json.dumps(plan), success=False
                )

    def test_release_dry_run_saves_without_publishing(self):
        self.run_script(
            "docker-plan/plan.py",
            PLAN='{"announcement_tag_is_implicit": true, "announcement_tag": "artifacts"}',
            GITHUB_EVENT_NAME="workflow_dispatch",
        )
        self.assertEqual(self.outputs()["mode"], "dry-run")
        self.assertEqual(self.outputs()["version"], "")
        self.assertEqual(self.outputs()["depot-project-id"], "production")
        self.assertEqual(self.outputs()["save"], "true")
        self.assertEqual(self.outputs()["publish"], "false")
        self.assertEqual(self.outputs()["login"], "false")

    def test_development_publication_uses_only_development_ghcr_repository(self):
        self.run_script("docker-plan/plan.py", PUSH_DEV="true")
        self.assertEqual(self.outputs()["mode"], "development")
        self.assertEqual(self.outputs()["images"], "ghcr.io/astral-sh/uv-dev")
        self.assertEqual(self.outputs()["depot-project-id"], "development")
        self.assertEqual(self.outputs()["save"], "true")
        self.assertEqual(self.outputs()["publish"], "true")

    def test_development_repository_uses_its_own_project_without_dockerhub_login(self):
        self.event.write_text(
            json.dumps(
                {"pull_request": {"head": {"repo": {"full_name": "astral-sh/uv-dev"}}}}
            )
        )
        self.run_script(
            "docker-plan/plan.py",
            PUSH_DEV="true",
            GITHUB_REPOSITORY="astral-sh/uv-dev",
            DEVELOPMENT_PROJECT="uvdev",
        )
        self.assertEqual(self.outputs()["depot-project-id"], "uvdev")
        self.assertEqual(self.outputs()["images"], "ghcr.io/astral-sh/uv-dev")
        self.assertEqual(self.outputs()["login"], "false")
        self.assertEqual(self.outputs()["publish"], "true")

    def test_development_publication_rejects_forks_and_release_plans(self):
        self.run_script(
            "docker-plan/plan.py",
            PUSH_DEV="true",
            PLAN='{"announcement_tag_is_implicit": false, "announcement_tag": "1.2.3"}',
            success=False,
        )
        self.event.write_text(
            json.dumps(
                {"pull_request": {"head": {"repo": {"full_name": "contributor/uv"}}}}
            )
        )
        self.run_script("docker-plan/plan.py", PUSH_DEV="true", success=False)
        self.run_script(
            "docker-plan/plan.py", GITHUB_REPOSITORY="contributor/uv", success=False
        )

    def test_other_astral_projects_use_the_same_registry_conventions(self):
        for name in ("ruff", "ty"):
            with self.subTest(name=name):
                self.run_script(
                    "docker-plan/plan.py",
                    NAME=name,
                    GITHUB_REPOSITORY=f"astral-sh/{name}",
                    GITHUB_EVENT_NAME="workflow_dispatch",
                    DOCKERHUB="false",
                    PLAN='{"announcement_tag_is_implicit": false, "announcement_tag": "1.2.3"}',
                )
                self.assertEqual(self.outputs()["images"], f"ghcr.io/astral-sh/{name}")
                self.assertEqual(self.outputs()["mode"], "release")

    def test_release_checks_project_version_and_orders_full_version_first(self):
        (self.path / "pyproject.toml").write_text(
            '[tool.example]\nversion = "9.9.9"\n\n[project]\nversion = "1.2.3"\n'
        )
        self.run_script("docker-build/metadata.py", MODE="release", VERSION="1.2.3")
        self.assertEqual(
            self.outputs(),
            {
                "tags": "type=pep440,pattern={{ version }},value=1.2.3\n"
                "type=pep440,pattern={{ major }}.{{ minor }},value=1.2.3",
                "flavor": "latest=auto",
            },
        )
        result = self.run_script(
            "docker-build/metadata.py", MODE="release", VERSION="9.9.9", success=False
        )
        self.assertIn("does not match project.version '1.2.3'", result.stderr)

    def test_release_requires_static_project_version(self):
        (self.path / "pyproject.toml").write_text('[project]\ndynamic = ["version"]\n')
        self.run_script(
            "docker-build/metadata.py", MODE="release", VERSION="1.2.3", success=False
        )

    def test_base_dry_run_needs_no_checkout_or_release_version(self):
        self.run_script("docker-build/metadata.py")
        self.assertEqual(
            self.outputs(), {"tags": "type=raw,value=dry-run", "flavor": "latest=auto"}
        )

    def test_base_development_build_uses_only_sha_tags(self):
        self.run_script("docker-build/metadata.py", MODE="development")
        self.assertEqual(self.outputs(), {"tags": "type=sha", "flavor": "latest=auto"})

    def test_release_variants_use_validated_version_and_never_tag_latest(self):
        self.run_script(
            "docker-build/metadata.py",
            MODE="release",
            VERSION="1.2.3",
            ALIASES="alpine3.23\nalpine\n",
        )
        self.assertEqual(
            self.outputs(),
            {
                "tags": "type=pep440,pattern={{ version }},suffix=-alpine3.23,value=1.2.3\n"
                "type=pep440,pattern={{ major }}.{{ minor }},suffix=-alpine3.23,value=1.2.3\n"
                "type=raw,value=alpine3.23\n"
                "type=pep440,pattern={{ version }},suffix=-alpine,value=1.2.3\n"
                "type=pep440,pattern={{ major }}.{{ minor }},suffix=-alpine,value=1.2.3\n"
                "type=raw,value=alpine",
                "flavor": "latest=false",
            },
        )

    def test_dry_run_variants_do_not_parse_a_placeholder_version(self):
        self.run_script("docker-build/metadata.py", ALIASES="alpine3.23\nalpine")
        self.assertEqual(
            self.outputs(),
            {
                "tags": "type=raw,value=alpine3.23\ntype=raw,value=alpine",
                "flavor": "latest=false",
            },
        )

    def test_development_variants_do_not_move_release_aliases(self):
        self.run_script(
            "docker-build/metadata.py", MODE="development", ALIASES="alpine3.23\nalpine"
        )
        self.assertEqual(
            self.outputs(),
            {
                "tags": "type=sha,suffix=-alpine3.23\ntype=sha,suffix=-alpine",
                "flavor": "latest=false",
            },
        )

    def test_metadata_rejects_unknown_modes_and_injected_tag_rules(self):
        self.run_script("docker-build/metadata.py", MODE="unknown", success=False)
        self.run_script(
            "docker-build/metadata.py", ALIASES="alpine,enable=true", success=False
        )
        self.run_script(
            "docker-build/metadata.py",
            MODE="release",
            VERSION="1.2.3\nDOCKER_TAGS",
            success=False,
        )


if __name__ == "__main__":
    unittest.main()
