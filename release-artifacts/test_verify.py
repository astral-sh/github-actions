import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).parent))

from verify import verify, verify_native


class VerifyNativeTest(unittest.TestCase):
    @patch("verify.subprocess.run")
    @patch("verify.sys.platform", "darwin")
    def test_macos_binary_identifiers(self, run) -> None:
        identifiers = '{"uv":"sh.astral.uv","uvx":"sh.astral.uvx"}'

        verify_native(
            Path("signed"),
            Path("extracted"),
            ["uv", "uvx"],
            identifiers,
        )

        self.assertEqual(
            run.call_args.args[0],
            [
                "uv",
                "run",
                "--locked",
                Path(__file__).with_name("verify-release-binaries-macos.py"),
                "--binary-identifiers",
                identifiers,
                Path("signed"),
                Path("extracted"),
                "uv",
                "uvx",
            ],
        )

    @patch("verify.sys.platform", "darwin")
    def test_missing_macos_binary_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing macOS"):
            verify_native(Path("signed"), Path("extracted"), ["uv"], "{}")


class VerifyTest(unittest.TestCase):
    @patch("verify.verify_native")
    @patch("verify.write_binaries")
    @patch("verify.check_archive_binaries")
    @patch("verify.read_archive", return_value={"uv": b"uv"})
    @patch("verify.read_wheels", return_value={"uv": b"uv", "uvx": b"uvx"})
    @patch("verify.sys.platform", "darwin")
    def test_archive_uses_binary_identifier_subset(
        self,
        _read_wheels: Mock,
        _read_archive: Mock,
        _check_archive_binaries: Mock,
        _write_binaries: Mock,
        verify_native_mock: Mock,
    ) -> None:
        target = Mock(github_archive=Path("uv.tar.gz"), github_members=[])

        verify(
            target,
            Path("signed"),
            Path("wheels"),
            Path("archives"),
            '{"uv":"sh.astral.uv","uvx":"sh.astral.uvx"}',
        )

        temporary = verify_native_mock.call_args_list[0].args[1].parent
        self.assertEqual(
            verify_native_mock.call_args_list,
            [
                call(
                    Path("signed"),
                    temporary / "wheels",
                    ["uv", "uvx"],
                    '{"uv":"sh.astral.uv","uvx":"sh.astral.uvx"}',
                ),
                call(
                    Path("signed"),
                    temporary / "github",
                    ["uv"],
                    '{"uv":"sh.astral.uv"}',
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
