import hashlib
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import verify
from artifacts import Target, Wheel


class MetadataVerificationTest(unittest.TestCase):
    def test_windows_identity_includes_guid_and_age(self) -> None:
        with patch.object(verify, "llvm_tool", return_value=Path("llvm-readobj")):
            with patch.object(
                verify,
                "run",
                return_value="PDBGUID: {abcd-1234}\nPDBAge: 2\n",
            ) as command:
                self.assertEqual(
                    verify.binary_identity(Path("uv.exe"), "windows"),
                    {"guid": "ABCD-1234", "age": 2},
                )
                command.assert_called_once_with(
                    Path("llvm-readobj"), "--coff-debug-directory", Path("uv.exe")
                )
            with (
                patch.object(verify, "run", return_value=""),
                self.assertRaisesRegex(ValueError, "Expected one PDB identity"),
            ):
                verify.binary_identity(Path("uv.exe"), "windows")

    def test_macos_identity_includes_each_architecture(self) -> None:
        with patch.object(
            verify,
            "run",
            return_value="UUID: abcd-5678 (x86_64) uv\nUUID: abcd-1234 (arm64) uv\n",
        ) as command:
            self.assertEqual(
                verify.binary_identity(Path("uv"), "macos"),
                {"uuids": [["ABCD-1234", "arm64"], ["ABCD-5678", "x86_64"]]},
            )
            command.assert_called_once_with("xcrun", "dwarfdump", "--uuid", Path("uv"))
        with (
            patch.object(verify, "run", return_value=""),
            self.assertRaisesRegex(ValueError, "Missing Mach-O UUID"),
        ):
            verify.binary_identity(Path("uv"), "macos")

    def test_sbom_checks_section_bytes_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "uv"
            data = zlib.compress(b'{"packages": []}')
            binary.write_bytes(b"header" + data + b"signature")
            with (
                patch.object(verify, "llvm_tool", return_value=Path("llvm-readobj")),
                patch.object(
                    verify,
                    "run",
                    return_value=f"Section {{\nName: .dep-v0\nOffset: 6\nSize: {len(data)}\n}}",
                ),
            ):
                self.assertEqual(
                    verify.sbom_digest(binary, "macos"),
                    hashlib.sha256(data).hexdigest(),
                )
                binary.write_bytes(b"header" + zlib.compress(b"invalid JSON"))
                with self.assertRaises(ValueError):
                    verify.sbom_digest(binary, "macos")

    def test_windows_sbom_uses_raw_section_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "uv.exe"
            data = zlib.compress(b'{"packages": []}') + bytes(16)
            binary.write_bytes(b"PE" + data)
            with (
                patch.object(verify, "llvm_tool", return_value=Path("llvm-readobj")),
                patch.object(
                    verify,
                    "run",
                    return_value=f"Section {{\nName: .dep-v0\nPointerToRawData: 0x2\nRawDataSize: {len(data)}\n}}",
                ),
            ):
                self.assertEqual(
                    verify.sbom_digest(binary, "windows"),
                    hashlib.sha256(data).hexdigest(),
                )
            with (
                patch.object(verify, "llvm_tool", return_value=Path("llvm-readobj")),
                patch.object(verify, "run", return_value="Section {\nName: .text\n}"),
                self.assertRaisesRegex(ValueError, "Missing embedded SBOM"),
            ):
                verify.sbom_digest(binary, "windows")

    def test_metadata_checks_selected_packages_before_and_after_signing(self) -> None:
        target = Target(
            "x86_64-pc-windows-msvc",
            "windows",
            [
                Wheel("uv", Path("wheels"), ["uv.exe", "uvx.exe", "uvw.exe"]),
                Wheel("uv_build", Path("wheels"), ["uv-build.exe"]),
            ],
            Path("uv.zip"),
            ["uv.exe", "uvx.exe", "uvw.exe"],
        )
        with (
            patch.object(
                verify, "binary_identity", return_value={"guid": "ABC", "age": 1}
            ) as identity,
            patch.object(verify, "sbom_digest", return_value="same-sbom") as sbom,
        ):
            verify.verify_metadata(target, Path("unsigned"), Path("signed"), ["uv"])
            self.assertEqual(identity.call_count, 6)
            self.assertEqual(sbom.call_count, 6)
            for name in target.wheels[0].binaries:
                identity.assert_any_call(Path("unsigned") / name, "windows")
                identity.assert_any_call(Path("signed") / name, "windows")
                sbom.assert_any_call(Path("unsigned") / name, "windows")
                sbom.assert_any_call(Path("signed") / name, "windows")
            identity.side_effect = [
                {"guid": "ABC", "age": 1},
                {"guid": "ABC", "age": 2},
            ]
            with self.assertRaisesRegex(
                ValueError, "Signing changed the debug identity"
            ):
                verify.verify_metadata(target, Path("unsigned"), Path("signed"), ["uv"])
            identity.side_effect = None
            sbom.side_effect = ["original", "changed"]
            with self.assertRaisesRegex(
                ValueError, "Signing changed the embedded SBOM"
            ):
                verify.verify_metadata(target, Path("unsigned"), Path("signed"), ["uv"])

    def test_unknown_or_duplicate_package_is_rejected(self) -> None:
        target = Target(
            "aarch64-apple-darwin",
            "macos",
            [Wheel("uv", Path("wheels"), ["uv", "uvx"])],
            Path("uv.tar.gz"),
            ["uv/uv", "uv/uvx"],
        )
        with self.assertRaisesRegex(ValueError, "distinct declared wheel packages"):
            verify.verify_metadata(
                target, Path("unsigned"), Path("signed"), ["missing"]
            )
        with self.assertRaisesRegex(ValueError, "distinct declared wheel packages"):
            verify.verify_metadata(
                target, Path("unsigned"), Path("signed"), ["uv", "uv"]
            )


if __name__ == "__main__":
    unittest.main()
