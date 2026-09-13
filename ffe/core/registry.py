"""Format detection + parser registry.

UI never branches on format names; it calls detect() then the registry.
"""
from __future__ import annotations

from typing import Callable, Optional

from .datasource import DataSource
from .model import ParseResult


class FormatParser:
    name = "unknown"
    magic: bytes = b""

    def probe(self, src: DataSource) -> bool:
        return src.read(0, len(self.magic)) == self.magic

    def parse(self, src: DataSource) -> ParseResult:  # pragma: no cover - abstract
        raise NotImplementedError


_REGISTRY: list[FormatParser] = []


def register(parser_cls: type[FormatParser]) -> type[FormatParser]:
    _REGISTRY.append(parser_cls())
    return parser_cls


def detect(src: DataSource) -> Optional[FormatParser]:
    """Magic bytes first, then probe() for formats whose magic isn't a prefix
    (e.g. RIFF/WAVE). Extension is never consulted."""
    head = src.read(0, 64)
    for p in _REGISTRY:
        if p.magic and head[: len(p.magic)] == p.magic:
            return p
    for p in _REGISTRY:
        if p.probe(src):
            return p
    return None


def parse_file(src: DataSource) -> Optional[ParseResult]:
    parser = detect(src)
    if parser is None:
        return None
    return parser.parse(src)


def registered_formats() -> list[str]:
    return [p.name for p in _REGISTRY]


def load_parsers() -> None:
    # Import side-effects register built-in parsers. Kept explicit and cheap.
    from ..parsers import elf, jpeg, mp4, pe, png, sqlite, wav, zip  # noqa: F401
