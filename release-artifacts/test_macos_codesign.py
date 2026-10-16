import unittest

from macos_codesign import signing_identifier, signing_identifiers


class SigningIdentifiersTest(unittest.TestCase):
    def test_identifiers(self) -> None:
        value = '{"uv":"sh.astral.uv","uvx":"sh.astral.uvx"}'

        self.assertEqual(
            signing_identifiers(value, ["uv", "uvx"]),
            {"uv": "sh.astral.uv", "uvx": "sh.astral.uvx"},
        )

    def test_identifier_paths_must_match_binaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "paths differ"):
            signing_identifiers('{"uv":"sh.astral.uv"}', ["uv", "uvx"])

    def test_identifier_paths_must_not_include_other_binaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "paths differ"):
            signing_identifiers('{"uv":"sh.astral.uv","uvx":"sh.astral.uvx"}', ["uv"])

    def test_identifiers_must_be_non_empty_strings(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty strings"):
            signing_identifiers('{"uv":""}', ["uv"])


class SigningIdentifierTest(unittest.TestCase):
    def test_identifier(self) -> None:
        details = "Executable=/tmp/uv\nIdentifier=sh.astral.uv\nTimestamp=...\n"

        self.assertEqual(signing_identifier(details, "uv"), "sh.astral.uv")

    def test_missing_identifier(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected one.*uv"):
            signing_identifier("Executable=/tmp/uv\nTimestamp=...\n", "uv")

    def test_multiple_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected one.*uv"):
            signing_identifier("Identifier=first\nIdentifier=second\n", "uv")


if __name__ == "__main__":
    unittest.main()
