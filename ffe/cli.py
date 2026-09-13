"""ffe CLI: inspect / validate / info / report / diff."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import inspect as ffe_inspect
from .core.model import Node


def _tree_lines(node: Node, depth: int = 0, max_depth: int = 3, out: list | None = None) -> list[str]:
    if out is None:
        out = []
    label = node.name
    if node.value is not None and not node.children:
        label += f" = {node.value}"
    if node.validation == "error":
        label += "  [ERROR]"
    elif node.validation == "warning":
        label += "  [WARN]"
    out.append("  " * depth + ("└─ " if depth else "") + label)
    if depth < max_depth:
        for c in node.children:
            _tree_lines(c, depth + 1, max_depth, out)
    elif node.children:
        out.append("  " * (depth + 1) + "…")
    return out


def cmd_inspect(args: argparse.Namespace) -> int:
    result = ffe_inspect(args.file)
    if result is None:
        print(f"Unrecognized format: {args.file}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
        return 0
    print(f"Format : {result.format_name}")
    print(f"Size   : {result.file_size} bytes")
    image = result.root.metadata.get("image", {})
    if image.get("width"):
        extras = [f"{k} {v}" for k, v in image.items()
                  if k not in ("width", "height") and v is not None]
        print(f"Image  : {image['width']} x {image['height']}"
              + (", " + ", ".join(extras) if extras else ""))
    for m in result.messages:
        print(f"Note   : {m}")
    print()
    print("\n".join(_tree_lines(result.root, max_depth=args.depth)))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    result = ffe_inspect(args.file)
    if result is None:
        print(f"Unrecognized format: {args.file}", file=sys.stderr)
        return 1
    errors = [n for n in result.root.walk() if n.validation == "error"]
    if errors:
        print(f"INVALID ({len(errors)} error(s))")
        for e in errors[:20]:
            print(f"  ✗ {e.path_string()}: {e.description}")
        return 1
    print("VALID")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    result = ffe_inspect(args.file)
    if result is None:
        print(f"Unrecognized format: {args.file}", file=sys.stderr)
        return 1
    print(json.dumps({"format": result.format_name, "fileSize": result.file_size,
                      "messages": result.messages,
                      "image": result.root.metadata.get("image", {}), "ok": result.ok},
                     indent=2, ensure_ascii=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    result = ffe_inspect(args.file)
    if result is None:
        print(f"Unrecognized format: {args.file}", file=sys.stderr)
        return 1
    if args.json:
        text = json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str)
    else:
        errors = [n for n in result.root.walk() if n.validation == "error"]
        warnings = [n for n in result.root.walk() if n.validation == "warning"]
        lines = [
            f"# {result.format_name} Analysis: {Path(args.file).name}",
            "",
            f"- File size: {result.file_size} bytes",
            f"- Status: {'INVALID' if errors else ('WARNING' if warnings else 'VALID')}",
            f"- Errors: {len(errors)}, Warnings: {len(warnings)}",
        ]
        image = result.root.metadata.get("image") or {}
        audio = result.root.metadata.get("audio") or {}
        archive = result.root.metadata.get("zip") or {}
        pe = result.root.metadata.get("pe") or {}
        if image.get("width"):
            lines.append(f"- Image: {image['width']} x {image['height']}"
                         + (f", {image.get('colorTypeName', str(image.get('components', '')) + ' components')}"
                            if image.get("colorTypeName") or image.get("components") else ""))
        if audio.get("sampleRate"):
            lines.append(f"- Audio: {audio.get('codec')}, {audio.get('channels')} ch, "
                         f"{audio.get('sampleRate')} Hz, {audio.get('bitsPerSample')} bit"
                         + (f", {audio.get('duration')}" if audio.get("duration") else ""))
        if archive:
            lines.append(f"- Archive: {archive.get('entries')} entries, "
                         f"methods {', '.join(archive.get('methods', []))}")
        if pe:
            lines.append(f"- PE: {pe.get('machine')}, {pe.get('subsystem')}, "
                         f"entry point RVA 0x{pe.get('entryPoint', 0):X}, "
                         f"{len(pe.get('sections', []))} sections"
                         + (", DLL" if pe.get("isDll") else ""))
            imp = pe.get("imports") or {}
            if imp:
                lines.append(f"- Imports: {imp.get('dlls')} DLLs, {imp.get('functions')} functions")
            exp = pe.get("exports") or {}
            if exp:
                lines.append(f"- Exports: {exp.get('dllName')} ({exp.get('names')} names)")
            lines.append("- Sections:")
            lines += [f"  - {s['name']:<8} raw 0x{s['rawOff']:X} ({s['rawSize']} B) {s['flags']}"
                      for s in pe.get("sections", [])]
        if result.messages:
            lines += ["", "## Notes", *[f"- {m}" for m in result.messages]]
        if errors or warnings:
            lines += ["", "## Validation"]
            lines += [f"- ✗ {e.path_string()}: {e.description}" for e in errors]
            lines += [f"- ⚠ {w.path_string()}: {w.description}" for w in warnings]
        lines += ["", "## Structure", "", "```text",
                  *"\n".join(_tree_lines(result.root, max_depth=args.depth)).splitlines(),
                  "```", ""]
        text = "\n".join(lines)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(text)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    from .core.diff import diff_files
    d = diff_files(args.file_a, args.file_b)
    if args.json:
        print(json.dumps(d.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"A: {d.file_a}  ({d.format_a or 'unrecognized'}, {d.size_a} bytes)")
    print(f"B: {d.file_b}  ({d.format_b or 'unrecognized'}, {d.size_b} bytes)")
    print(f"Common prefix: {d.common_prefix_len} bytes; "
          f"differing bytes: {d.differing_bytes} in {len(d.byte_runs)} run(s)"
          + ("  [TRUNCATED — results are partial]" if d.truncated else ""))
    for off_a, off_b, length in d.byte_runs[:args.runs]:
        print(f"  0x{off_a:X} (A) / 0x{off_b:X} (B): {length} bytes differ")
    if len(d.byte_runs) > args.runs:
        print(f"  … {len(d.byte_runs) - args.runs} more run(s)")
    if d.same_format:
        if d.added or d.removed or d.changed:
            print()
            print("Structural differences:")
            for p, v in d.added[:20]:
                print(f"  + {p} = {v}")
            for p, v in d.removed[:20]:
                print(f"  - {p} = {v}")
            for p, va, vb in d.changed[:20]:
                print(f"  ~ {p}: {va} → {vb}")
        else:
            print("Structurally identical.")
    else:
        print("(different or unrecognized formats — no structural comparison)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ffe", description="File Format Explorer")
    sub = ap.add_subparsers(dest="command", required=True)

    p_ins = sub.add_parser("inspect", help="Parse a file and show its structure tree")
    p_ins.add_argument("file")
    p_ins.add_argument("--json", action="store_true", help="Output JSON")
    p_ins.add_argument("--depth", type=int, default=3, help="Tree depth limit (default 3)")
    p_ins.set_defaults(func=cmd_inspect)

    p_val = sub.add_parser("validate", help="Check structural validity")
    p_val.add_argument("file")
    p_val.set_defaults(func=cmd_validate)

    p_info = sub.add_parser("info", help="Brief summary as JSON")
    p_info.add_argument("file")
    p_info.set_defaults(func=cmd_info)

    p_rep = sub.add_parser("report", help="Export analysis report (Markdown or JSON)")
    p_rep.add_argument("file")
    p_rep.add_argument("--json", action="store_true", help="JSON instead of Markdown")
    p_rep.add_argument("-o", "--output", help="Write to file (default: stdout)")
    p_rep.add_argument("--depth", type=int, default=3, help="Tree depth limit (default 3)")
    p_rep.set_defaults(func=cmd_report)

    p_diff = sub.add_parser("diff", help="Compare two files (bytes + structure)")
    p_diff.add_argument("file_a")
    p_diff.add_argument("file_b")
    p_diff.add_argument("--json", action="store_true")
    p_diff.add_argument("--runs", type=int, default=20, help="Max byte runs to show")
    p_diff.set_defaults(func=cmd_diff)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
