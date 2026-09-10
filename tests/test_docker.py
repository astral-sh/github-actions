import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "a" * 64
FINAL_DIGEST = "sha256:" + "b" * 64


class DockerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.output = self.path / "output"
        self.output.touch()
        self.calls = self.path / "calls"
        self.calls.touch()
        self.environment = dict(
            os.environ, RUNNER_TEMP=str(self.path), GITHUB_OUTPUT=str(self.output)
        )

    def run_script(self, script, *, success=True, **environment):
        result = subprocess.run(
            ["bash", str(ROOT / script)],
            env=dict(self.environment, **environment),
            text=True,
            capture_output=True,
            check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def image(self, name="ruff"):
        return {
            "name": name,
            "build_id": "build123",
            "digest": DIGEST,
            "tags": [
                f"ghcr.io/astral-sh/{name}:1.2.3",
                f"ghcr.io/astral-sh/{name}:latest",
            ],
            "annotations": [
                "index:org.opencontainers.image.description=spaces; $and `quotes`"
            ],
        }

    def test_record(self):
        record = self.image()
        self.run_script(
            "docker-build/record.sh",
            NAME=record["name"],
            BUILD_ID=record["build_id"],
            DIGEST=DIGEST,
            TAGS="\n".join(record["tags"]),
            ANNOTATIONS="\n".join(record["annotations"]),
        )
        self.assertEqual(
            json.loads((self.path / "docker-image-record.json").read_text()), record
        )
        self.run_script(
            "docker-build/record.sh",
            success=False,
            NAME="../ruff",
            BUILD_ID="build123",
            DIGEST=DIGEST,
            TAGS="",
            ANNOTATIONS="",
        )

    def test_variants(self):
        for product, binaries, extra in [
            ("uv", "uv uvx", 'ENV UV_TOOL_BIN_DIR="/usr/local/bin"'),
            ("ruff", "ruff", ""),
            ("ty", "ty", ""),
        ]:
            with self.subTest(product=product):
                self.output.write_text("")
                self.run_script(
                    "docker-variant/prepare.sh",
                    IMAGE_MAPPING="alpine:3.23,alpine3.23,alpine",
                    SOURCE_IMAGE=f"registry.depot.dev/project@{DIGEST}",
                    BINARIES=binaries,
                    COMMAND=product,
                    DOCKERFILE_LINES=extra,
                    VERSION="1.2.3",
                    PUSH_DEV="false",
                )
                expected = (
                    f"FROM alpine:3.23\nCOPY --from=registry.depot.dev/project@{DIGEST}"
                    + "".join(f" /{binary}" for binary in binaries.split())
                    + " /usr/local/bin/\n"
                    + (extra + "\n" if extra else "")
                    + f'ENTRYPOINT []\nCMD ["/usr/local/bin/{product}"]\n'
                )
                self.assertEqual(
                    (self.path / "docker-variant.Dockerfile").read_text(), expected
                )
                self.assertIn("name=alpine3.23\n", self.output.read_text())
                self.assertIn(
                    "type=pep440,pattern={{ version }},suffix=-alpine3.23,value=1.2.3\n",
                    self.output.read_text(),
                )
        self.output.write_text("")
        self.run_script(
            "docker-variant/prepare.sh",
            IMAGE_MAPPING="alpine:3.23,alpine3.23,alpine",
            SOURCE_IMAGE="ghcr.io/astral-sh/ty:latest",
            BINARIES="ty",
            COMMAND="ty",
            DOCKERFILE_LINES="",
            VERSION="sha",
            PUSH_DEV="true",
        )
        self.assertIn(
            "type=sha,suffix=-alpine3.23\ntype=sha,suffix=-alpine\n",
            self.output.read_text(),
        )
        self.assertNotIn("pep440", self.output.read_text())

    def test_manifest_requires_exact_names(self):
        records = self.path / "records"
        for name in ["ruff", "alpine3.23"]:
            target = records / f"docker-image-{name}"
            target.mkdir(parents=True)
            (target / "docker-image-record.json").write_text(
                json.dumps(self.image(name))
            )
        environment = {
            "BASE_NAME": "ruff",
            "IMAGE_MAPPINGS": '["alpine:3.23,alpine3.23,alpine"]',
            "RECORDS_PATH": str(records),
        }
        self.run_script("docker-manifest/assemble.sh", **environment)
        self.assertEqual(
            json.loads((self.path / "docker-manifest.json").read_text()),
            {"base": self.image(), "extra": [self.image("alpine3.23")]},
        )
        record_path = records / "docker-image-alpine3.23/docker-image-record.json"
        for name in ["unexpected", "ruff"]:
            record_path.write_text(json.dumps(self.image(name)))
            self.run_script("docker-manifest/assemble.sh", success=False, **environment)

    def publisher(
        self, record, *, success=True, images="ghcr.io/astral-sh/ruff", **environment
    ):
        binaries = self.path / "bin"
        binaries.mkdir(exist_ok=True)
        for name in ["docker", "depot"]:
            executable = binaries / name
            shutil.copyfile(ROOT / "tests/docker-cli-stub.py", executable)
            executable.chmod(0o755)
        self.calls.write_text("")
        return self.run_script(
            "docker-publish/publish.sh",
            success=success,
            PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
            CALLS=str(self.calls),
            DEPOT_PROJECT_ID="project",
            IMAGE_JSON=json.dumps(record),
            IMAGES=images,
            ATTESTATION_IMAGE="ghcr.io/astral-sh/ruff",
            DIGEST=DIGEST,
            FINAL_DIGEST=FINAL_DIGEST,
            **environment,
        )

    def test_publish_keeps_full_index_and_annotations(self):
        record = self.image()
        record["tags"].append("docker.io/astral/ruff:1.2.3")
        self.publisher(record, images="ghcr.io/astral-sh/ruff\ndocker.io/astral/ruff\n")
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        pushes = [call for call in calls if call[:2] == ["depot", "push"]]
        self.assertEqual(
            pushes,
            [
                ["depot", "push", "--project", "project", "--tag", tag, "build123"]
                for tag in [record["tags"][0], record["tags"][2]]
            ],
        )
        creates = [
            call
            for call in calls
            if call[:4] == ["docker", "buildx", "imagetools", "create"]
        ]
        self.assertEqual(len(creates), 2)
        self.assertIn(record["annotations"][0], creates[0])
        self.assertEqual(creates[0][-1], f"ghcr.io/astral-sh/ruff@{DIGEST}")
        self.assertEqual(creates[1][-1], f"docker.io/astral/ruff@{DIGEST}")
        self.assertIn(f"digest={FINAL_DIGEST}\n", self.output.read_text())

    def test_publish_rejects_untrusted_destinations_before_login(self):
        for invalid_tag in [
            "ghcr.io/astral-sh/ruff-dev:latest",
            "ghcr.io/astral-sh/ruff:bad tag",
            "ghcr.io/astral-sh/ruff:latest\n--help",
        ]:
            record = self.image()
            record["tags"].append(invalid_tag)
            self.publisher(record, success=False)
            self.assertEqual(self.calls.read_text(), "")
        self.publisher(
            self.image(),
            success=False,
            images="ghcr.io/astral-sh/ruff\ndocker.io/astral/ruff",
        )
        self.assertEqual(self.calls.read_text(), "")

    def test_publish_rejects_digest_mismatches(self):
        self.publisher(self.image(), success=False, SAVED_DIGEST=FINAL_DIGEST)
        self.assertNotIn('"push"', self.calls.read_text())
        self.publisher(self.image(), success=False, COPIED_DIGEST=FINAL_DIGEST)
        self.assertNotIn('"create"', self.calls.read_text())


if __name__ == "__main__":
    unittest.main()
