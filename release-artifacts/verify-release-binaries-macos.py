# /// script
# requires-python = ">=3.12"
# dependencies = ["cryptography"]
#
# [tool.uv]
# no-build = true
# exclude-newer = "P7D"
# ///
"""Verify packaged macOS executables against the signing job's output.

Require each executable to contain exactly the signed bytes.
For each executable, `codesign` must accept its Apple-rooted signature and
report the configured signing identifier and a signing timestamp. The embedded
leaf certificate must match the certificate pinned by the signing job.
"""

import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from macos_codesign import signing_identifier, signing_identifiers


def verify_binaries(
    signed: Path,
    directory: Path,
    binaries: list[str],
    identifiers: dict[str, str],
) -> None:
    """Check packaged bytes, Apple trust, identifiers, and signing metadata."""
    found = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
    if found != set(binaries):
        raise ValueError(f"Unexpected packaged executables: {sorted(found)}")
    certificate = x509.load_pem_x509_certificate(
        (signed / "certificate.pem").read_bytes()
    )
    expected_certificate = certificate.fingerprint(hashes.SHA256())
    with tempfile.TemporaryDirectory() as temporary:
        for index, binary in enumerate(binaries):
            path = directory / binary
            if (signed / binary).read_bytes() != path.read_bytes():
                raise ValueError(
                    f"Packaged executable differs from signing output: {binary}"
                )
            subprocess.run(
                [
                    "codesign",
                    "--verify",
                    "--strict",
                    "-R",
                    "=anchor apple generic",
                    path,
                ],
                check=True,
            )
            details = subprocess.check_output(
                ["codesign", "--display", "--verbose=4", path],
                stderr=subprocess.STDOUT,
                text=True,
            )
            actual_identifier = signing_identifier(details, binary)
            expected_identifier = identifiers[binary]
            if actual_identifier != expected_identifier:
                raise ValueError(
                    f"Unexpected signing identifier for {binary}: "
                    f"expected {expected_identifier!r}, found {actual_identifier!r}"
                )
            if not any(line.startswith("Timestamp=") for line in details.splitlines()):
                raise ValueError(f"Missing signing timestamp: {binary}")

            prefix = Path(temporary) / f"{index}-cert-"
            subprocess.run(
                ["codesign", "--display", f"--extract-certificates={prefix}", path],
                check=True,
            )
            actual_certificate = hashlib.sha256(
                Path(f"{prefix}0").read_bytes()
            ).digest()
            if actual_certificate != expected_certificate:
                raise ValueError(f"Signing certificate differs from expected: {binary}")


def main() -> None:
    """Verify the named executables against the signer's output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary-identifiers", required=True)
    parser.add_argument("signed", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("binaries", nargs="+")
    args = parser.parse_args()

    try:
        identifiers = signing_identifiers(args.binary_identifiers, args.binaries)
        verify_binaries(args.signed, args.directory, args.binaries, identifiers)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
