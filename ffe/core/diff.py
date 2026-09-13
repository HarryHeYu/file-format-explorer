"""Diff engine: raw byte differences + structural (tree-based) differences.

Compares two files via their ParseResults:
- byte ranges that differ (merged into coarse runs for readability)
- structure: nodes compared by path — added / removed / changed values
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..api import inspect as ffe_inspect
from .model import ParseResult

BYTE_RUN_MERGE = 16     # merge differing bytes closer than this into one run
MAX_BYTE_RUNS = 256


@dataclass
class DiffResult:
    file_a: str
    file_b: str
    format_a: str | None
    format_b: str | None
    size_a: int = 0
    size_b: int = 0
    same_format: bool = True
    byte_runs: list = field(default_factory=list)       # (off_a, off_b, length)
    differing_bytes: int = 0
    common_prefix_len: int = 0
    truncated: bool = False
    added: list = field(default_factory=list)           # (path, value)
    removed: list = field(default_factory=list)
    changed: list = field(default_factory=list)         # (path, value_a, value_b)

    def to_dict(self) -> dict:
        return {
            "fileA": self.file_a, "fileB": self.file_b,
            "formatA": self.format_a, "formatB": self.format_b,
            "sizeA": self.size_a, "sizeB": self.size_b,
            "sameFormat": self.same_format,
            "byteRuns": [list(r) for r in self.byte_runs],
            "differingBytes": self.differing_bytes,
            "commonPrefixLen": self.common_prefix_len,
            "truncated": self.truncated,
            "added": [list(x) for x in self.added],
            "removed": [list(x) for x in self.removed],
            "changed": [list(x) for x in self.changed],
        }


def _byte_diff(path_a: str, path_b: str) -> tuple[list, int, int, int]:
    """Returns (runs, differing, common_prefix, truncated_flag)."""
    runs: list[tuple[int, int, int]] = []
    differing = 0
    prefix = 0
    chunk = 1 << 20
    truncated = 0
    with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
        base = 0
        pending_start = None
        pending_end = None
        while True:
            ca = fa.read(chunk)
            cb = fb.read(chunk)
            if not ca and not cb:
                break
            n = max(len(ca), len(cb))
            for i in range(n):
                a = ca[i] if i < len(ca) else None
                b = cb[i] if i < len(cb) else None
                if a != b:
                    differing += 1
                    off = base + i
                    if pending_start is None:
                        pending_start = pending_end = off
                    elif off - pending_end <= BYTE_RUN_MERGE:
                        pending_end = off
                    else:
                        runs.append((pending_start, pending_start, pending_end - pending_start + 1))
                        if len(runs) >= MAX_BYTE_RUNS:
                            truncated = 1
                            return runs, differing, prefix, truncated
                        pending_start = pending_end = off
                elif pending_start is None and base + i == prefix:
                    prefix += 1
            base += n
        if pending_start is not None:
            runs.append((pending_start, pending_start, pending_end - pending_start + 1))
    return runs, differing, prefix, truncated


def diff_files(path_a: str, path_b: str, max_items: int = 200) -> DiffResult:
    res = DiffResult(file_a=path_a, file_b=path_b, format_a=None, format_b=None)
    ra: ParseResult | None = ffe_inspect(path_a)
    rb: ParseResult | None = ffe_inspect(path_b)
    res.format_a = ra.format_name if ra else None
    res.format_b = rb.format_name if rb else None
    res.size_a = ra.file_size if ra else 0
    res.size_b = rb.file_size if rb else 0
    res.same_format = res.format_a == res.format_b and res.format_a is not None

    runs, differing, prefix, truncated = _byte_diff(path_a, path_b)
    res.byte_runs = runs
    res.differing_bytes = differing
    res.common_prefix_len = prefix
    res.truncated = bool(truncated)

    if res.same_format and ra and rb:
        # rename duplicate node paths (e.g. two "tEXt" chunks) by adding #k
        def flatten_unique(root):
            flat: dict[str, object] = {}
            seen: dict[str, int] = {}

            def rec(node, prefix):
                path = f"{prefix}/{node.name}" if prefix else node.name
                if node.value is not None or (not node.children and node.kind != "container"):
                    k = seen.get(path, 0)
                    seen[path] = k + 1
                    key = path if k == 0 else f"{path}#{k}"
                    flat[key] = node.value
                for c in node.children:
                    rec(c, path)
            rec(root, "")
            return flat

        fa = flatten_unique(ra.root)
        fb = flatten_unique(rb.root)
        for k in list(fa.keys()):
            if k not in fb:
                res.removed.append((k, str(fa[k])))
            elif fa[k] != fb[k]:
                res.changed.append((k, str(fa[k]), str(fb[k])))
        for k in fb:
            if k not in fa:
                res.added.append((k, str(fb[k])))
        res.removed = res.removed[:max_items]
        res.added = res.added[:max_items]
        res.changed = res.changed[:max_items]
    return res
