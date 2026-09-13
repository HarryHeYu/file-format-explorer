"""ZIP parser.

Parses End of Central Directory → Central Directory entries → Local File
Headers → file data. The headline feature is the cross-link between each
Central Directory entry and its Local File Header (metadata.relation),
plus CRC32 verification of every file's data. Malformed input never raises.
"""
from __future__ import annotations

import struct
import zlib

from ..core.datasource import DataSource, u16le, u32le
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

METHODS = {0: "Stored", 1: "Shrink", 8: "Deflate", 9: "Deflate64",
           12: "Bzip2", 14: "LZMA"}

SIG_EOCD = b"PK\x05\x06"
SIG_CD = b"PK\x01\x02"
SIG_LOCAL = b"PK\x03\x04"


def _dos_datetime(dos_date: int, dos_time: int) -> str:
    try:
        year = ((dos_date >> 9) & 0x7F) + 1980
        month = (dos_date >> 5) & 0x0F
        day = dos_date & 0x1F
        hour = (dos_time >> 11) & 0x1F
        minute = (dos_time >> 5) & 0x3F
        second = (dos_time & 0x1F) * 2
        return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
    except Exception:  # noqa: BLE001
        return "invalid"


@register
class ZIPParser(FormatParser):
    name = "ZIP"
    magic = b""  # probe(): EOCD must exist near EOF

    def probe(self, src: DataSource) -> bool:
        if self._find_eocd(src) is not None:
            return True
        # starts with a local header but no EOCD → likely truncated ZIP
        return src.read(0, 4) == SIG_LOCAL

    @staticmethod
    def _find_eocd(src: DataSource) -> int | None:
        """Scan the last 64KB+22 for the EOCD signature (comment may follow)."""
        window = min(src.size, 22 + 65535 + 4)
        tail = src.read(src.size - window, window)
        i = tail.rfind(SIG_EOCD)
        if i < 0:
            return None
        return src.size - window + i

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="ZIP", kind="container", offset=0, size=src.size,
                    description="Zip archive")

        eocd_off = self._find_eocd(src)
        if eocd_off is None:
            # no EOCD: if it starts with a local header, salvage what we can
            if src.read(0, 4) == SIG_LOCAL:
                messages.append("EOCD not found — scanning local headers of a "
                                "truncated archive")
                return self._salvage_locals(src, root, messages)
            root.add(Node("EOCD missing", kind="error", offset=0, size=0,
                          validation="error",
                          description="End of Central Directory not found — "
                                      "not a ZIP or badly truncated"))
            messages.append("EOCD not found")
            root.link_parents()
            return ParseResult(format_name="ZIP", file_size=src.size, root=root,
                               messages=messages)

        # ---- EOCD ----
        eocd = Node("EOCD", kind="container", offset=eocd_off,
                    size=min(22, src.size - eocd_off),
                    description="End of Central Directory record")
        raw = src.read(eocd_off, 22)
        (_disk, _cd_disk, n_disk, n_total, cd_size, cd_off, _cmt) = struct.unpack(
            "<HHHHIIH", raw[4:22])
        eocd.add(Node("Signature", kind="field", offset=eocd_off, size=4,
                      value="PK\\x05\\x06", data_type="magic", raw=raw[0:4]))
        eocd.add(Node("Entries (this disk)", kind="field", offset=eocd_off + 8, size=2,
                      value=n_disk, data_type="uint16", endian="little", raw=raw[8:10]))
        eocd.add(Node("Entries (total)", kind="field", offset=eocd_off + 10, size=2,
                      value=n_total, data_type="uint16", endian="little", raw=raw[10:12]))
        eocd.add(Node("Central Directory size", kind="field", offset=eocd_off + 12, size=4,
                      value=cd_size, data_type="uint32", endian="little", raw=raw[12:16]))
        eocd.add(Node("Central Directory offset", kind="field", offset=eocd_off + 16, size=4,
                      value=cd_off, data_type="uint32", endian="little", raw=raw[16:20]))
        root.add(eocd)

        if cd_off + cd_size > src.size:
            messages.append(f"Central Directory at {cd_off}+{cd_size} exceeds file size "
                            f"{src.size} — falling back to a local-header scan")
            root.add(Node("Central Directory unreachable", kind="error",
                          offset=cd_off, size=0, validation="error",
                          description=f"CD range 0x{cd_off:X}+{cd_size} exceeds file"))
            return self._salvage_locals(src, root, messages)

        # ---- Central Directory ----
        cd_node = Node("Central Directory", kind="container", offset=cd_off, size=cd_size,
                       description=f"{n_total} entr(y/ies), authoritative metadata")
        root.add(cd_node)
        entries = []
        pos = cd_off
        for _ in range(n_total):
            head = src.read(pos, 46)
            if head[:4] != SIG_CD or len(head) < 46:
                messages.append(f"Bad Central Directory entry at 0x{pos:X}")
                cd_node.add(Node("Bad entry", kind="error", offset=pos, size=4,
                                 validation="error",
                                 description="Expected PK\\x01\\x02 signature"))
                break
            (vmade, vneed, flags, method, mtime_time, mtime_date, crc,
             csize, usize, nlen, elen, clen, _disk_start, _iattr, _eattr,
             local_off) = struct.unpack("<HHHHHHIIIHHHHHII", head[4:46])
            name_raw = src.read(pos + 46, nlen)
            name = name_raw.decode("utf-8", "replace")
            entry = Node(name or "(unnamed)", kind="container", offset=pos,
                         size=46 + nlen + elen + clen,
                         description=f"Central Directory entry for {name!r}")
            entry.add(Node("Signature", kind="field", offset=pos, size=4,
                           value="PK\\x01\\x02", data_type="magic", raw=head[0:4]))
            entry.add(Node("Filename", kind="field", offset=pos + 46, size=nlen,
                           value=name, data_type="string", raw=name_raw))
            entry.add(Node("Modified", kind="field", offset=pos + 12, size=4,
                           value=_dos_datetime(mtime_date, mtime_time), data_type="timestamp",
                           description="DOS date+time"))
            entry.add(Node("Compression", kind="field", offset=pos + 10, size=2,
                           value=METHODS.get(method, f"0x{method:04X}"),
                           data_type="uint16", endian="little", raw=head[10:12]))
            entry.add(Node("Compressed size", kind="field", offset=pos + 20, size=4,
                           value=csize, data_type="uint32", endian="little", raw=head[20:24]))
            entry.add(Node("Uncompressed size", kind="field", offset=pos + 24, size=4,
                           value=usize, data_type="uint32", endian="little", raw=head[24:28]))
            entry.add(Node("CRC32", kind="field", offset=pos + 16, size=4,
                           value=f"0x{crc:08X}", data_type="uint32", endian="little",
                           raw=head[16:20]))
            off_node = Node("Local header offset", kind="field", offset=pos + 42, size=4,
                            value=local_off, data_type="uint32", endian="little",
                            raw=head[42:46])
            entry.add(off_node)
            cd_node.add(entry)
            entries.append({
                "name": name, "flags": flags, "method": method, "crc": crc,
                "csize": csize, "usize": usize, "local_off": local_off,
                "entry_node": entry,
            })
            pos += 46 + nlen + elen + clen

        # ---- Local File Headers + data ----
        locals_node = Node("Local Entries", kind="container", offset=0, size=0,
                           description="Local File Headers + compressed data "
                                       "(the bytes you would stream)")
        root.add(locals_node)
        local_by_off: dict[int, Node] = {}
        for ent in entries:
            lo = ent["local_off"]
            head = src.read(lo, 30)
            if head[:4] != SIG_LOCAL or len(head) < 30:
                locals_node.add(Node(f"Bad local header for {ent['name']!r}",
                                     kind="error", offset=lo, size=max(0, min(4, src.size - lo)),
                                     validation="error",
                                     description="Expected PK\\x03\\x04 signature"))
                messages.append(f"Local header for {ent['name']!r} missing/bad at 0x{lo:X}")
                continue
            nlen = u16le(head, 26)
            elen = u16le(head, 28)
            name_raw = src.read(lo + 30, nlen)
            name = name_raw.decode("utf-8", "replace")
            data_off = lo + 30 + nlen + elen

            lnode = Node(name or "(unnamed)", kind="container", offset=lo,
                         size=min(30 + nlen + elen + ent["csize"], src.size - lo),
                         description=f"Local File Header for {name!r}")
            lnode.add(Node("Signature", kind="field", offset=lo, size=4,
                           value="PK\\x03\\x04", data_type="magic", raw=head[0:4]))
            lnode.add(Node("Filename", kind="field", offset=lo + 30, size=nlen,
                           value=name, data_type="string", raw=name_raw))
            flags = u16le(head, 6)
            method = u16le(head, 8)
            lnode.add(Node("Compression", kind="field", offset=lo + 8, size=2,
                           value=METHODS.get(method, f"0x{method:04X}"),
                           data_type="uint16", endian="little", raw=head[8:10]))
            if flags & 0x08:
                lnode.add(Node("Sizes/CRC", kind="info", offset=lo + 14, size=12,
                               description="Data descriptor mode (bit 3): sizes "
                                           "written after the data, zeros here"))
            else:
                lnode.add(Node("CRC32", kind="field", offset=lo + 14, size=4,
                               value=f"0x{u32le(head, 14):08X}", data_type="uint32",
                               endian="little", raw=head[14:18]))
                lnode.add(Node("Compressed size", kind="field", offset=lo + 18, size=4,
                               value=u32le(head, 18), data_type="uint32",
                               endian="little", raw=head[18:22]))
                lnode.add(Node("Uncompressed size", kind="field", offset=lo + 22, size=4,
                               value=u32le(head, 22), data_type="uint32",
                               endian="little", raw=head[22:26]))

            data = src.read(data_off, ent["csize"])
            if len(data) < ent["csize"]:
                lnode.validation = "error"
                lnode.add(Node("File data", kind="error", offset=data_off,
                               size=len(data), validation="error",
                               description=f"Truncated: header claims {ent['csize']} bytes, "
                                           f"only {len(data)} remain"))
                messages.append(f"Data for {ent['name']!r} truncated")
            else:
                ok, note = self._verify(ent, data)
                dnode = Node("File data", kind="data", offset=data_off, size=ent["csize"],
                             description=f"{ent['csize']} compressed bytes at 0x{data_off:X}"
                                         + (f" → {ent['usize']} bytes" if ent["method"] == 8 else ""))
                dnode.validation = "ok" if ok else "error"
                dnode.description += f" — CRC {'valid' if ok else 'MISMATCH (' + note + ')'}"
                lnode.add(dnode)
                if not ok:
                    messages.append(f"CRC mismatch for {ent['name']!r}: {note}")
            locals_node.add(lnode)
            local_by_off[lo] = lnode
        if locals_node.children:
            first, last = locals_node.children[0], locals_node.children[-1]
            locals_node.offset = first.offset
            locals_node.size = last.end - first.offset

        # ---- relations: central entry ↔ local header ----
        for ent in entries:
            local = local_by_off.get(ent["local_off"])
            if local is not None:
                ent["entry_node"].metadata["relation"] = {
                    "label": "Local File Header",
                    "nodeId": local.id,
                }
                ent["entry_node"].description += (
                    f" — Local File Header at 0x{ent['local_off']:X}")

        files = [e for e in entries if not e["name"].endswith("/")]
        root.metadata["zip"] = {
            "entries": len(entries), "files": len(files),
            "methods": sorted({METHODS.get(e["method"], hex(e["method"])) for e in entries}),
            "uncompressedTotal": sum(e["usize"] for e in entries),
            "compressedTotal": sum(e["csize"] for e in entries),
        }
        root.link_parents()
        return ParseResult(format_name="ZIP", file_size=src.size, root=root,
                           messages=messages)

    @staticmethod
    def _salvage_locals(src: DataSource, root: Node, messages: list) -> ParseResult:
        """Sequential local-header scan for archives without a usable CD."""
        pos = 0
        salvaged = Node("Local Entries", kind="container", offset=0, size=0,
                        description="Salvaged from sequential scan (no Central "
                                    "Directory available)")
        root.add(salvaged)
        while pos + 30 <= src.size and src.read(pos, 4) == SIG_LOCAL:
            nlen = u16le(src.read(pos + 26, 2), 0)
            elen = u16le(src.read(pos + 28, 2), 0)
            csize = u32le(src.read(pos + 18, 4), 0)
            name = src.read(pos + 30, nlen).decode("utf-8", "replace")
            data_off = pos + 30 + nlen + elen
            avail = src.size - data_off
            node = Node(name or "(unnamed)", kind="container", offset=pos,
                        size=min(30 + nlen + elen + csize, src.size - pos))
            node.validation = "error" if avail < csize else ""
            node.add(Node("Filename", kind="field", offset=pos + 30, size=nlen,
                          value=name, data_type="string"))
            node.add(Node("File data", kind="data" if avail >= csize else "error",
                          offset=data_off, size=max(0, min(csize, avail)),
                          validation="error" if avail < csize else "ok",
                          description=f"claims {csize} bytes, {avail} available"
                                      if avail < csize else f"{csize} bytes"))
            salvaged.add(node)
            pos = data_off + csize
        if salvaged.children:
            first, last = salvaged.children[0], salvaged.children[-1]
            salvaged.offset = first.offset
            salvaged.size = last.end - first.offset
        root.metadata["zip"] = {"entries": len(salvaged.children), "files": None}
        root.link_parents()
        return ParseResult(format_name="ZIP", file_size=src.size, root=root,
                           messages=messages)

    @staticmethod
    def _verify(ent: dict, data: bytes) -> tuple[bool, str]:
        try:
            if ent["method"] == 0:
                payload = data
            elif ent["method"] == 8:
                payload = zlib.decompressobj(-15).decompress(data)
            else:
                return True, "method not verified"  # structure still shown
            if len(payload) != ent["usize"]:
                return False, f"uncompressed size {len(payload)} != declared {ent['usize']}"
            crc = zlib.crc32(payload) & 0xFFFFFFFF
            if crc != ent["crc"]:
                return False, f"computed 0x{crc:08X} != stored 0x{ent['crc']:08X}"
            return True, ""
        except zlib.error as e:
            return False, f"decompress failed: {e}"
