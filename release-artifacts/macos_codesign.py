"""Parse macOS code-signing configuration and metadata."""

import json


def signing_identifiers(value: str, binaries: list[str]) -> dict[str, str]:
    """Require an identifier for each packaged binary and no others."""
    identifiers = json.loads(value)
    if not isinstance(identifiers, dict) or not all(
        isinstance(path, str) and path and isinstance(identifier, str) and identifier
        for path, identifier in identifiers.items()
    ):
        raise ValueError(
            "Binary identifiers must map binary paths to non-empty strings"
        )
    if identifiers.keys() != set(binaries):
        binary_paths = set(binaries)
        missing = sorted(binary_paths - identifiers.keys())
        unexpected = sorted(identifiers.keys() - binary_paths)
        raise ValueError(
            "Binary identifier paths differ from packaged binaries: "
            f"missing={missing}, unexpected={unexpected}"
        )
    return identifiers


def signing_identifier(details: str, binary: str) -> str:
    """Return the single signing identifier reported by `codesign`."""
    identifiers = [
        line.removeprefix("Identifier=")
        for line in details.splitlines()
        if line.startswith("Identifier=")
    ]
    if len(identifiers) != 1 or not identifiers[0]:
        raise ValueError(f"Expected one code-signing identifier: {binary}")
    return identifiers[0]
