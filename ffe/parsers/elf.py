"""ELF parser (32/64-bit, little/big endian).

Parses the ELF header → program headers (segments) → section headers →
string tables → symbol tables. Field-level everything, bounded loops,
bounds-checked offsets. Malformed input degrades to error nodes.
"""
from __future__ import annotations

import struct

from ..core.datasource import DataSource
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

ETYPES = {0: "ET_NONE", 1: "ET_REL", 2: "ET_EXEC", 3: "ET_DYN", 4: "ET_CORE"}
EMACHINES = {
    3: "x86", 8: "MIPS", 40: "ARM", 62: "x86-64", 183: "AArch64",
    20: "PowerPC", 50: "IA-64",
}
STYPES = {
    0: "SHT_NULL", 1: "SHT_PROGBITS", 2: "SHT_SYMTAB", 3: "SHT_STRTAB",
    4: "SHT_RELA", 5: "SHT_HASH", 6: "SHT_DYNAMIC", 7: "SHT_NOTE",
    8: "SHT_NOBITS", 9: "SHT_REL", 11: "SHT_DYNSYM", 14: "SHT_INIT_ARRAY",
}
PTYPES = {
    0: "PT_NULL", 1: "PT_LOAD", 2: "PT_DYNAMIC", 3: "PT_INTERP",
    4: "PT_NOTE", 6: "PT_PHDR", 7: "PT_TLS",
}
SFLAGS = [(0x1, "WRITE"), (0x2, "ALLOC"), (0x4, "EXECINSTR"), (0x40, "MERGE"),
          (0x80, "STRINGS"), (0x400, "INFO_LINK")]

MAX_SECTIONS = 1024
MAX_SEGMENTS = 256
MAX_SYMBOLS = 16384


def _sflags(v: int) -> str:
    return "|".join(n for b, n in SFLAGS if v & b) or f"0x{v:X}"


@register
class ELFParser(FormatParser):
    name = "ELF"
    magic = b"\x7fELF"

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="ELF", kind="container", offset=0, size=src.size,
                    description="Executable and Linkable Format")
        root.metadata["elf"] = {}

        ident = src.read(0, 16)
        if ident[:4] != b"\x7fELF":
            root.add(Node("Magic", kind="error", offset=0, size=4, validation="error",
                          description="Not an ELF magic"))
            messages.append("ELF magic missing")
            root.link_parents()
            return ParseResult(format_name="ELF", file_size=src.size, root=root,
                               messages=messages)
        if len(ident) < 16:
            return self._bail(root, messages, src, "File shorter than the 16-byte e_ident")
        is64 = ident[4] == 2
        big = ident[5] == 2
        if ident[4] not in (1, 2) or ident[5] not in (1, 2):
            root.add(Node("EI_CLASS/EI_DATA", kind="error", offset=4, size=2,
                          validation="error",
                          description=f"Invalid ELF class {ident[4]} or data encoding {ident[5]}"))
            messages.append("Invalid ELF class/data encoding in e_ident")
            root.link_parents()
            return ParseResult(format_name="ELF", file_size=src.size, root=root,
                               messages=messages)
        e = ">" if big else "<"
        root.add(Node("Magic", kind="field", offset=0, size=4,
                      value="7f 45 4c 46", data_type="magic", raw=ident[:4]))
        root.add(Node("Class", kind="field", offset=4, size=1,
                      value="ELF64" if is64 else "ELF32", data_type="uint8",
                      raw=ident[4:5]))
        root.add(Node("Endianness", kind="field", offset=5, size=1,
                      value="Big Endian" if big else "Little Endian",
                      data_type="uint8", raw=ident[5:6]))
        root.add(Node("OS ABI", kind="field", offset=7, size=1,
                      value={0: "SysV", 3: "Linux", 6: "Solaris"}.get(ident[7], str(ident[7])),
                      data_type="uint8", raw=ident[7:8]))

        # ---- header fields ----
        if is64:
            fmt = e + "HHIQQQIHHHHHH"
            raw = src.read(16, 48)
            if len(raw) < 48:
                return self._bail(root, messages, src, "Truncated ELF header")
            (etype, machine, version, entry, phoff, shoff, flags,
             ehsize, phentsize, phnum, shentsize, shnum, shstrndx) = struct.unpack(fmt, raw)
            hdr_base = 16
        else:
            fmt = e + "HHIIIIIHHHHHH"
            raw = src.read(16, 36)
            if len(raw) < 36:
                return self._bail(root, messages, src, "Truncated ELF header")
            (etype, machine, version, entry, phoff, shoff, eflags32,
             ehsize, phentsize, phnum, shentsize, shnum, shstrndx) = struct.unpack(fmt, raw)
        hdr = Node("ELF Header", kind="container", offset=0, size=ehsize if is64 else ehsize)
        root.add(hdr)
        type_name = ETYPES.get(etype, f"0x{etype:04X}")
        mach_name = EMACHINES.get(machine, f"0x{machine:04X}")
        hdr.add(Node("Type", kind="field", offset=16, size=2, value=type_name,
                     data_type="uint16", endian=e, raw=raw[0:2],
                     description="EXEC=executable, DYN=shared object/PIE"))
        hdr.add(Node("Machine", kind="field", offset=18, size=2, value=mach_name,
                     data_type="uint16", endian=e, raw=raw[2:4]))
        if is64:
            hdr.add(Node("Entry point", kind="field", offset=24, size=8,
                         value=f"0x{entry:X}", data_type="uint64", endian=e, raw=raw[8:16]))
            hdr.add(Node("Program header offset", kind="field", offset=32, size=8,
                         value=phoff, data_type="uint64", endian=e, raw=raw[16:24]))
            hdr.add(Node("Section header offset", kind="field", offset=40, size=8,
                         value=shoff, data_type="uint64", endian=e, raw=raw[24:32]))
            hdr.add(Node("Number of program headers", kind="field", offset=56, size=2,
                         value=phnum, data_type="uint16", endian=e, raw=raw[40:42]))
            hdr.add(Node("Number of sections", kind="field", offset=60, size=2,
                         value=shnum, data_type="uint16", endian=e, raw=raw[44:46]))
        else:
            hdr.add(Node("Entry point", kind="field", offset=24, size=4,
                         value=f"0x{entry:X}", data_type="uint32", endian=e, raw=raw[8:12]))
            hdr.add(Node("Program header offset", kind="field", offset=28, size=4,
                         value=phoff, data_type="uint32", endian=e, raw=raw[12:16]))
            hdr.add(Node("Section header offset", kind="field", offset=32, size=4,
                         value=shoff, data_type="uint32", endian=e, raw=raw[16:20]))
            hdr.add(Node("Number of program headers", kind="field", offset=44, size=2,
                         value=phnum, data_type="uint16", endian=e, raw=raw[28:30]))
            hdr.add(Node("Number of sections", kind="field", offset=48, size=2,
                         value=shnum, data_type="uint16", endian=e, raw=raw[30:32]))
        root.metadata["elf"].update({"class": "ELF64" if is64 else "ELF32",
                                     "machine": mach_name, "type": type_name,
                                     "entry": entry, "endian": "big" if big else "little"})

        # extended encodings: shnum==0 → real count in section 0's sh_size;
        # shstrndx==SHN_XINDEX → real index in section 0's sh_link
        real_shnum, real_shstrndx = shnum, shstrndx
        if shoff and shnum == 0:
            need_s = 64 if is64 else 40
            raw0 = src.read(shoff, need_s)
            if len(raw0) >= need_s:
                if is64:
                    real_shnum = struct.unpack(e + "Q", raw0[32:40])[0]
                else:
                    real_shnum = struct.unpack(e + "I", raw0[20:24])[0]
                hdr.add(Node("Extended section count", kind="field",
                             value=real_shnum, data_type="uint64" if is64 else "uint32",
                             endian=e,
                             description="e_shnum==0: real count from section 0 sh_size"))
        if shstrndx == 0xFFFF and real_shnum:
            need_s = 64 if is64 else 40
            raw0 = src.read(shoff, need_s)
            if len(raw0) >= need_s:
                real_shstrndx = (struct.unpack(e + "I", raw0[40:44])[0] if is64
                                 else struct.unpack(e + "I", raw0[24:28])[0])
                hdr.add(Node("Extended shstrndx", kind="field",
                             value=real_shstrndx, data_type="uint32", endian=e,
                             description="SHN_XINDEX: real index from section 0 sh_link"))
        if real_shnum > MAX_SECTIONS:
            messages.append(f"Section count {real_shnum} exceeds safety cap "
                            f"{MAX_SECTIONS} — showing first {MAX_SECTIONS}")
            real_shnum = MAX_SECTIONS
        if phnum > MAX_SEGMENTS:
            messages.append(f"Program header count {phnum} exceeds safety cap "
                            f"{MAX_SEGMENTS} — showing first {MAX_SEGMENTS}")
        phnum = min(phnum, MAX_SEGMENTS)
        shnum = real_shnum
        shstrndx = real_shstrndx

        # ---- program headers ----
        if phoff and phnum:
            ph_node = Node("Program Headers", kind="container", offset=phoff,
                           size=phentsize * phnum,
                           description="Segments for the loader")
            root.add(ph_node)
            for i in range(phnum):
                off = phoff + i * phentsize
                raw_p = src.read(off, phentsize)
                need_p = 56 if is64 else 32
                if len(raw_p) < need_p:
                    ph_node.add(Node("Truncated segment entry", kind="error",
                                     offset=off, size=len(raw_p), validation="error"))
                    messages.append("Program header table truncated")
                    break
                raw_p = raw_p[:need_p]  # phentsize may exceed the exact record size
                if is64:
                    ptype, pflags, poff, pvaddr, _ppaddr, pfilesz, pmemsz, _pal = \
                        struct.unpack(e + "IIQQQQQQ", raw_p)
                else:
                    ptype, poff, pvaddr, _ppaddr, pfilesz, pmemsz, pflags, _pal = \
                        struct.unpack(e + "IIIIIIII", raw_p)
                seg = Node(PTYPES.get(ptype, f"0x{ptype:X}"), kind="container",
                           offset=off, size=phentsize)
                seg.add(Node("Type", kind="field", offset=off, size=4 if is64 else 4,
                             value=PTYPES.get(ptype, f"0x{ptype:X}"),
                             data_type="uint32", endian=e, raw=raw_p[0:4]))
                seg.add(Node("File offset", kind="field",
                             offset=off + (8 if is64 else 4), size=8 if is64 else 4,
                             value=poff, data_type="uint64" if is64 else "uint32",
                             endian=e))
                seg.add(Node("Virtual address", kind="field",
                             offset=off + (16 if is64 else 8), size=8 if is64 else 4,
                             value=f"0x{pvaddr:X}", data_type="uint64" if is64 else "uint32",
                             endian=e))
                seg.add(Node("File size", kind="field",
                             offset=off + (32 if is64 else 16), size=8 if is64 else 4,
                             value=pfilesz, data_type="uint64" if is64 else "uint32",
                             endian=e))
                if poff + pfilesz > src.size:
                    seg.validation = "error"
                    seg.add(Node("Out of bounds", kind="error", offset=off,
                                 size=phentsize, validation="error",
                                 description=f"Segment data 0x{poff:X}+{pfilesz} exceeds file"))
                    messages.append(f"Segment {PTYPES.get(ptype, ptype)} exceeds file boundary")
                ph_node.add(seg)

        # ---- section headers ----
        shstrtab_data = b""
        sections: list[dict] = []
        if shoff and shnum:
            sh_node = Node("Section Headers", kind="container",
                           offset=min(shoff, src.size),
                           size=max(0, min(shoff + shentsize * shnum, src.size) - shoff)
                           if shoff < src.size else 0)
            root.add(sh_node)
            # first pass: entries
            for i in range(shnum):
                off = shoff + i * shentsize
                raw_s = src.read(off, shentsize)
                need_s = 64 if is64 else 40
                if len(raw_s) < need_s:
                    sh_node.add(Node("Truncated section entry", kind="error",
                                     offset=off, size=len(raw_s), validation="error"))
                    messages.append("Section header table truncated")
                    break
                raw_s = raw_s[:need_s]  # shentsize may exceed the exact record size
                if is64:
                    name_off, styp, sflags, saddr, soff, ssize, slink, sinfo, _al, _es = \
                        struct.unpack(e + "IIQQQQIIQQ", raw_s)
                else:
                    name_off, styp, sflags, saddr, soff, ssize, slink, sinfo, _al, _es = \
                        struct.unpack(e + "IIIIIIIIII", raw_s)
                sections.append({"name_off": name_off, "type": styp, "flags": sflags,
                                 "addr": saddr, "off": soff, "size": ssize,
                                 "link": slink, "entsize": _es, "hdr_off": off})
            # resolve names via shstrtab
            if shstrndx < len(sections):
                st = sections[shstrndx]
                shstrtab_data = src.read(st["off"], min(st["size"], 1 << 20))
            for s in sections:
                s["name"] = _cstr_at(shstrtab_data, s["name_off"])

            for i, s in enumerate(sections):
                if s["type"] == 0 and i == 0:
                    continue  # skip null section detail
                sec = Node(s["name"] or f"section[{i}]", kind="container",
                           offset=s["hdr_off"], size=shentsize)
                sec.add(Node("Name", kind="field", offset=s["hdr_off"], size=4,
                             value=s["name"], data_type="uint32", endian=e,
                             description=f"offset {s['name_off']} into .shstrtab"))
                sec.add(Node("Type", kind="field", offset=s["hdr_off"] + 4, size=4,
                             value=STYPES.get(s["type"], f"0x{s['type']:X}"),
                             data_type="uint32", endian=e))
                sec.add(Node("Flags", kind="field", offset=s["hdr_off"] + 8,
                             size=8 if is64 else 4, value=_sflags(s["flags"]),
                             data_type="uint64" if is64 else "uint32", endian=e))
                sec.add(Node("Address", kind="field", offset=s["hdr_off"] + 16,
                             size=8 if is64 else 4, value=f"0x{s['addr']:X}",
                             data_type="uint64" if is64 else "uint32", endian=e))
                sec.add(Node("Offset", kind="field", offset=s["hdr_off"] + 24,
                             size=8 if is64 else 4, value=s["off"],
                             data_type="uint64" if is64 else "uint32", endian=e))
                sec.add(Node("Size", kind="field", offset=s["hdr_off"] + 32,
                             size=8 if is64 else 4, value=s["size"],
                             data_type="uint64" if is64 else "uint32", endian=e))
                if s["type"] not in (8,) and s["off"] and s["size"]:  # SHT_NOBITS has no file data
                    if s["off"] + s["size"] <= src.size:
                        sec.add(Node("Raw data", kind="data", offset=s["off"],
                                     size=s["size"],
                                     description=f"{s['size']} bytes at 0x{s['off']:X} "
                                                 f"(vaddr 0x{s['addr']:X})"))
                    else:
                        sec.validation = "error"
                        sec.add(Node("Out of bounds", kind="error", offset=s["hdr_off"],
                                     size=shentsize, validation="error",
                                     description=f"Section data 0x{s['off']:X}+{s['size']} "
                                                 f"exceeds file size {src.size}"))
                        messages.append(f"Section {s['name']!r} exceeds file boundary")
                # symbol tables
                if s["type"] in (2, 11) and s["off"] and s["size"] and s["off"] + s["size"] <= src.size:
                    self._parse_symbols(src, sec, s, sections, is64, e, messages)
                sh_node.add(sec)

        root.link_parents()
        return ParseResult(format_name="ELF", file_size=src.size, root=root,
                           messages=messages)

    def _parse_symbols(self, src: DataSource, sec: Node, s: dict,
                       sections: list, is64: bool, e: str, messages: list) -> None:
        entsize = 24 if is64 else 16
        count = s["size"] // entsize
        count = min(count, MAX_SYMBOLS)
        # linked strtab
        strtab = b""
        if s["link"] < len(sections):
            st = sections[s["link"]]
            strtab = src.read(st["off"], min(st["size"], 1 << 20))
        sym_node = Node("Symbols", kind="container", offset=s["off"], size=s["size"],
                        description=f"{count} symbols")
        sec.add(sym_node)
        named = 0
        for i in range(count):
            off = s["off"] + i * entsize
            raw = src.read(off, entsize)
            if len(raw) < entsize:
                break
            if is64:
                name_off, info, _other, shndx, value, size = struct.unpack(e + "IBBHQQ", raw)
            else:
                name_off, value, size, info, _other, shndx = struct.unpack(e + "IIIBBH", raw)
            name = _cstr_at(strtab, name_off)
            bind = ("LOCAL", "GLOBAL", "WEAK")[min(info >> 4, 2)] if info >> 4 < 3 else f"bind{info >> 4}"
            if name:
                sym_node.add(Node(name, kind="field", offset=off, size=entsize,
                                  value=f"0x{value:X} ({bind}, {size} B)",
                                  data_type="symbol", description=f"shndx {shndx}"))
                named += 1
        if named == 0:
            sym_node.add(Node("(no named symbols)", kind="info"))

    @staticmethod
    def _bail(root: Node, messages: list, src: DataSource, why: str) -> ParseResult:
        root.add(Node("Truncated header", kind="error", offset=0, size=src.size,
                      validation="error", description=why))
        messages.append(why)
        root.link_parents()
        return ParseResult(format_name="ELF", file_size=src.size, root=root,
                           messages=messages)


def _cstr_at(tab: bytes, off: int) -> str:
    if off <= 0 or off >= len(tab):
        return ""
    end = tab.find(b"\x00", off)
    return tab[off:end if end >= 0 else len(tab)].decode("utf-8", "replace")
