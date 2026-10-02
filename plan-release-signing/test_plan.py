import json
import sys
import unittest
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).parent))

from plan import package_inventories, signing_plan

TARGETS = [
    "aarch64-apple-darwin",
    "aarch64-unknown-linux-gnu",
    "aarch64-pc-windows-msvc",
    "x86_64-apple-darwin",
    "x86_64-pc-windows-msvc",
    "i686-pc-windows-msvc",
]

UV_PACKAGES = {
    "macos": {"uv": ["uv", "uvx"], "uv_build": ["uv-build"]},
    "windows": {
        "uv": ["uv.exe", "uvx.exe", "uvw.exe"],
        "uv_build": ["uv-build.exe"],
    },
}

RUFF_PACKAGES = {
    "macos": {"ruff": ["ruff"]},
    "windows": {"ruff": ["ruff.exe"]},
}


class SigningPlanTest(unittest.TestCase):
    def plan(self, packages: dict, archive_package: str) -> dict[str, list[dict]]:
        return signing_plan(
            TARGETS,
            package_inventories(json.dumps(packages)),
            archive_package,
            PurePosixPath("wheels"),
            PurePosixPath("github-archives"),
        )

    def test_uv_artifact_declarations(self) -> None:
        plan = self.plan(UV_PACKAGES, "uv")

        self.assertEqual(
            [target["target"] for target in plan["macos"]],
            ["aarch64-apple-darwin", "x86_64-apple-darwin"],
        )
        self.assertEqual(
            [target["target"] for target in plan["windows"]],
            [
                "aarch64-pc-windows-msvc",
                "i686-pc-windows-msvc",
                "x86_64-pc-windows-msvc",
            ],
        )
        self.assertEqual(
            plan["macos"][0]["github-archive-members"],
            [
                "uv-aarch64-apple-darwin/uv",
                "uv-aarch64-apple-darwin/uvx",
            ],
        )
        self.assertEqual(
            plan["windows"][0]["github-archive-members"],
            ["uv.exe", "uvx.exe", "uvw.exe"],
        )
        self.assertEqual(
            plan["windows"][0]["wheels"],
            [
                {
                    "package": "uv",
                    "directory": "wheels/aarch64-pc-windows-msvc",
                    "binaries": ["uv.exe", "uvx.exe", "uvw.exe"],
                },
                {
                    "package": "uv_build",
                    "directory": "wheels/aarch64-pc-windows-msvc",
                    "binaries": ["uv-build.exe"],
                },
            ],
        )

    def test_ruff_artifact_declarations(self) -> None:
        plan = self.plan(RUFF_PACKAGES, "ruff")

        self.assertEqual(
            plan["macos"][1]["github-archive"],
            "github-archives/ruff-x86_64-apple-darwin.tar.gz",
        )
        self.assertEqual(
            plan["windows"][2]["github-archive-members"],
            ["ruff.exe"],
        )

    def test_rejects_unsupported_native_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported release signing"):
            signing_plan(
                [*TARGETS, "arm64ec-pc-windows-msvc"],
                package_inventories(json.dumps(UV_PACKAGES)),
                "uv",
                PurePosixPath("wheels"),
                PurePosixPath("github-archives"),
            )

    def test_rejects_duplicate_executables(self) -> None:
        packages = {
            "macos": {"ruff": ["ruff"], "ruff_extra": ["ruff"]},
        }

        with self.assertRaisesRegex(ValueError, "executables must be distinct"):
            package_inventories(json.dumps(packages))


if __name__ == "__main__":
    unittest.main()
