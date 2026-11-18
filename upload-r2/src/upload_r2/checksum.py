"""Calculate R2 checksums over local files."""

from __future__ import annotations

from base64 import b64encode
from typing import TYPE_CHECKING
from zlib import crc32

from awscrt.checksums import crc64nvme

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

READ_SIZE = 1024 * 1024


def crc64nvme_checksum(path: Path) -> str:
    checksum = 0
    with path.open("rb") as file:
        while chunk := file.read(READ_SIZE):
            checksum = crc64nvme(chunk, checksum)
    return b64encode(checksum.to_bytes(8, "big")).decode("ascii")


def read_crc32(file: BinaryIO, size: int) -> bytes:
    checksum = 0
    while size:
        chunk = file.read(min(size, READ_SIZE))
        if not chunk:
            raise OSError("Source file ended while calculating CRC32")
        checksum = crc32(chunk, checksum)
        size -= len(chunk)
    return checksum.to_bytes(4, "big")


def crc32_checksum(path: Path, size: int, *, parts: tuple[int, ...] = ()) -> str:
    with path.open("rb") as file:
        if parts:
            composite = 0
            for part_size in parts:
                composite = crc32(read_crc32(file, part_size), composite)
            checksum = composite.to_bytes(4, "big")
            suffix = f"-{len(parts)}"
        else:
            checksum = read_crc32(file, size)
            suffix = ""
        if file.read(1):
            raise OSError("Source file grew while calculating CRC32")
    return b64encode(checksum).decode("ascii") + suffix
