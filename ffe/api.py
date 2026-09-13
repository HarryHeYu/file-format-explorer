"""High-level API shared by CLI and GUI."""
from __future__ import annotations

from pathlib import Path

from .core.datasource import DataSource
from .core.model import ParseResult
from .core.registry import load_parsers, parse_file

_loaded = False


def _ensure() -> None:
    global _loaded
    if not _loaded:
        load_parsers()
        _loaded = True


def inspect(path: str | Path) -> ParseResult | None:
    """Parse a file. Returns None if the format is not recognized."""
    _ensure()
    src = DataSource(str(path))
    try:
        return parse_file(src)
    finally:
        src.close()


def is_recognized(path: str | Path) -> bool:
    _ensure()
    src = DataSource(str(path))
    try:
        from .core.registry import detect
        return detect(src) is not None
    finally:
        src.close()
