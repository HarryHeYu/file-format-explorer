"""Streaming byte-pattern search over a file (server-side, bounded memory)."""
from __future__ import annotations


def parse_hex_query(text: str) -> bytes | None:
    """Accept '50 4B 03 04', '504b0304', or '0x504B' style hex."""
    t = text.strip().lower().removeprefix("0x").replace(" ", "").replace(",", "")
    if not t or len(t) % 2 or any(c not in "0123456789abcdef" for c in t):
        return None
    return bytes.fromhex(t)


def search_file(path: str, pattern: bytes, limit: int = 200,
                window: int = 1 << 20) -> list[int]:
    """Return up to `limit` absolute offsets of pattern occurrences.

    Reads the file in overlapping windows so memory stays bounded even for
    multi-GB files. Overlap = len(pattern) - 1 keeps matches that straddle
    window boundaries.
    """
    if not pattern:
        return []
    hits: list[int] = []
    overlap = len(pattern) - 1
    with open(path, "rb") as fh:
        base = 0
        tail = b""
        while True:
            chunk = fh.read(window)
            if not chunk:
                break
            buf = tail + chunk
            start = 0
            while True:
                i = buf.find(pattern, start)
                if i < 0:
                    break
                hits.append(base + i - len(tail))
                if len(hits) >= limit:
                    return hits
                start = i + 1
            tail = buf[-overlap:] if overlap else b""
            base += len(chunk)
    return hits
