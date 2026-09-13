"""Unified structure model shared by all parsers, the GUI and the CLI.

A ParseResult is a tree of Node objects. Every node records where it lives
in the raw file (offset/size) so the UI can highlight bytes and, going the
other way, locate the deepest node that owns a given byte.
"""
from __future__ import annotations

import base64
import itertools
from dataclasses import dataclass, field
from typing import Any, Optional

# thread-safe: gui_server parses concurrently (ThreadingHTTPServer)
_ids = itertools.count()


@dataclass
class Node:
    name: str
    kind: str = "field"          # container | field | data | error | info
    offset: int = 0              # absolute offset in file
    size: int = 0                # bytes covered (data range only, not children headers)
    value: Optional[Any] = None  # decoded value, if any
    description: str = ""
    data_type: str = ""          # uint32, chunk-type, string, ...
    endian: str = ""             # "big" | "little" | ""
    children: list["Node"] = field(default_factory=list)
    raw: Optional[bytes] = None  # raw bytes for small fields only
    validation: str = ""         # "ok" | "warning" | "error" (+ message in description)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = next(_ids)

    @property
    def end(self) -> int:
        return self.offset + self.size

    def add(self, *nodes: "Node") -> "Node":
        self.children.extend(nodes)
        return self

    def find_id(self, node_id: int) -> Optional["Node"]:
        if self.id == node_id:
            return self
        for c in self.children:
            got = c.find_id(node_id)
            if got is not None:
                return got
        return None

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def path(self) -> list["Node"]:
        """Chain from root to this node; requires nodes to have set parent."""
        node: Optional[Node] = self
        chain = []
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    def path_string(self) -> str:
        return " / ".join(n.name for n in self.path())

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "offset": self.offset,
            "size": self.size,
            "end": self.end,
            "value": _jsonable(self.value),
            "description": self.description,
            "dataType": self.data_type,
            "endian": self.endian,
            "path": self.path_string(),
            "validation": self.validation,
        }
        if self.metadata:
            d["metadata"] = {k: _jsonable(v) for k, v in self.metadata.items()}
        if self.raw is not None:
            d["rawHex"] = self.raw.hex(" ")
        d["children"] = [c.to_dict() for c in self.children]
        return d

    # parent links ---------------------------------------------------------
    def link_parents(self, parent: Optional["Node"] = None) -> None:
        self.parent = parent
        for c in self.children:
            c.link_parents(self)


Node.parent = None  # type: ignore[attr-defined]


def _jsonable(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.hex(" ")
    return v


@dataclass
class ParseResult:
    format_name: str
    file_size: int
    root: Node
    messages: list[str] = field(default_factory=list)  # human-facing info/warnings

    @property
    def ok(self) -> bool:
        """True iff no node in the tree carries a validation error."""
        return all(n.validation != "error" for n in self.root.walk())

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format_name,
            "fileSize": self.file_size,
            "ok": self.ok,
            "messages": self.messages,
            "root": self.root.to_dict(),
        }


def base64_of(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
