"""Data source abstraction: lazy, bounded reads from a file (or bytes).

Never loads the whole file; the Hex view asks for small windows.
"""
from __future__ import annotations

import os
from typing import Optional


class DataSource:
    def __init__(self, path: Optional[str] = None, data: Optional[bytes] = None):
        if data is not None:
            self._data = data
            self._fh = None
        else:
            self._data = None
            self._fh = open(path, "rb")
        self.size = len(self._data) if self._data is not None else os.path.getsize(path)  # type: ignore[arg-type]
        self.path = path

    def read(self, offset: int, length: int) -> bytes:
        """Read up to `length` bytes; silently clamps at EOF. Never raises on bounds."""
        if offset < 0:
            offset = 0
        if offset >= self.size or length <= 0:
            return b""
        length = min(length, self.size - offset)
        if self._data is not None:
            return self._data[offset:offset + length]
        self._fh.seek(offset)
        return self._fh.read(length)

    def __enter__(self) -> "DataSource":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()


def u16be(b: bytes, off: int = 0) -> int:
    return int.from_bytes(b[off:off + 2], "big")


def u16le(b: bytes, off: int = 0) -> int:
    return int.from_bytes(b[off:off + 2], "little")


def u32be(b: bytes, off: int = 0) -> int:
    return int.from_bytes(b[off:off + 4], "big")


def u32le(b: bytes, off: int = 0) -> int:
    return int.from_bytes(b[off:off + 4], "little")
