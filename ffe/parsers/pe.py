"""PE (Portable Executable) parser.

Walks DOS Header → DOS Stub → PE Signature → COFF Header → Optional Header
(PE32/PE32+) → Data Directories → Section Table → Imports → Exports.
All loops are bounded; malformed input degrades into error nodes, never
exceptions. RVA→file-offset mapping goes through the section table.
"""
from __future__ import annotations

import struct

from ..core.datasource import DataSource
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

MACHINES = {
    0x014C: "i386", 0x8664: "x64", 0xAA64: "ARM64", 0x01C4: "ARM",
    0x0200: "IA64", 0x01C0: "ARM or Thumb",
}
SUBSYSTEMS = {
    1: "Native", 2: "Windows GUI", 3: "Windows Console", 5: "OS/2 Console",
    7: "POSIX Console", 9: "Windows CE GUI", 10: "EFI application",
    14: "EFI boot driver",
}
DIRECTORY_NAMES = [
    "Export Table", "Import Table", "Resource Table", "Exception Table",
    "Certificate Table", "Base Relocation Table", "Debug", "Architecture",
    "Global Ptr", "TLS Table", "Load Config", "Bound Import", "IAT",
    "Delay Import Descriptor", "CLR Runtime Header", "Reserved",
]
DIR_EXPORT, DIR_IMPORT, DIR_RESOURCE, DIR_RELOC, DIR_IAT = 0, 1, 2, 5, 12

# safety caps — malformed files must not spin the parser
MAX_SECTIONS = 96
MAX_IMPORT_DLLS = 512
MAX_IMPORT_FUNCS = 8192
MAX_EXPORT_NAMES = 4096

CHAR_FLAGS = [
    (0x20, "CODE"), (0x40, "INITIALIZED_DATA"), (0x80, "UNINITIALIZED_DATA"),
    (0x02000000, "DISCARDABLE"), (0x10000000, "SHARED"),
    (0x20000000, "EXECUTE"), (0x40000000, "READ"), (0x80000000, "WRITE"),
]


def _flags_str(ch: int) -> str:
    return "|".join(name for bit, name in CHAR_FLAGS if ch & bit) or f"0x{ch:08X}"


@register
class PEParser(FormatParser):
    name = "PE"
    magic = b"MZ"

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="PE", kind="container", offset=0, size=src.size,
                    description="Portable Executable image")
        root.metadata["pe"] = {}

        # ---- DOS header ----
        dos = Node("DOS Header", kind="container", offset=0, size=64,
                   description="MS-DOS compatibility header")
        root.add(dos)
        head2 = src.read(0, 2)
        dos.add(Node("e_magic", kind="field", offset=0, size=2, value="MZ",
                     data_type="magic", raw=head2, description="MZ = Mark Zbikowski"))
        if head2 != b"MZ":
            dos.validation = "error"
            messages.append("MZ magic missing")
        e_lfanew = u32_at(src, 0x3C)
        if e_lfanew is None or e_lfanew == 0 or e_lfanew + 4 > src.size or e_lfanew > 0x10000:
            root.add(Node("Invalid e_lfanew", kind="error", offset=0x3C, size=4,
                          validation="error",
                          description=f"PE header offset 0x{e_lfanew or 0:X} is out of range"))
            messages.append("Invalid e_lfanew")
            root.link_parents()
            return ParseResult(format_name="PE", file_size=src.size, root=root,
                               messages=messages)
        dos.add(Node("e_lfanew", kind="field", offset=0x3C, size=4, value=e_lfanew,
                     data_type="uint32", endian="little",
                     raw=src.read(0x3C, 4), description="Offset of the PE header"))

        # ---- DOS stub ----
        stub_len = e_lfanew - 64
        if stub_len > 0:
            root.add(Node("DOS Stub", kind="data", offset=64, size=stub_len,
                          description="Legacy MS-DOS program (usually 'This program "
                                      "cannot be run in DOS mode')"))

        # ---- PE signature ----
        pe_sig = src.read(e_lfanew, 4)
        if pe_sig != b"PE\x00\x00":
            root.add(Node("PE Signature", kind="error", offset=e_lfanew, size=4,
                          validation="error",
                          description=f"Expected PE\\0\\0, found {pe_sig.hex(' ') or 'EOF'}"))
            messages.append("PE signature missing or corrupted")
            root.link_parents()
            return ParseResult(format_name="PE", file_size=src.size, root=root,
                               messages=messages)
        root.add(Node("PE Signature", kind="field", offset=e_lfanew, size=4,
                      value="PE\\0\\0", data_type="magic", raw=pe_sig))

        # ---- COFF header ----
        coff_off = e_lfanew + 4
        c = src.read(coff_off, 20)
        if len(c) < 20:
            root.add(Node("COFF Header", kind="error", offset=coff_off, size=len(c),
                          validation="error", description="Truncated COFF header"))
            messages.append("Truncated COFF header")
            root.link_parents()
            return ParseResult(format_name="PE", file_size=src.size, root=root,
                               messages=messages)
        (machine, n_sections, timestamp, _sym_ptr, _n_syms,
         opt_size, characteristics) = struct.unpack("<HHIIIHH", c)
        coff = Node("COFF Header", kind="container", offset=coff_off, size=20)
        root.add(coff)
        mach_name = MACHINES.get(machine, f"0x{machine:04X}")
        coff.add(Node("Machine", kind="field", offset=coff_off, size=2,
                      value=mach_name, data_type="uint16", endian="little", raw=c[0:2]))
        coff.add(Node("NumberOfSections", kind="field", offset=coff_off + 2, size=2,
                      value=n_sections, data_type="uint16", endian="little", raw=c[2:4]))
        coff.add(Node("TimeDateStamp", kind="field", offset=coff_off + 4, size=4,
                      value=timestamp, data_type="uint32", endian="little", raw=c[4:8],
                      description="Link time (Unix seconds)"))
        coff.add(Node("Characteristics", kind="field", offset=coff_off + 18, size=2,
                      value=_coff_chars(characteristics), data_type="flags",
                      endian="little", raw=c[18:20],
                      description="DLL?" + str(bool(characteristics & 0x2000))))
        root.metadata["pe"]["machine"] = mach_name
        root.metadata["pe"]["isDll"] = bool(characteristics & 0x2000)
        if n_sections > MAX_SECTIONS:
            messages.append(f"NumberOfSections={n_sections} looks bogus (>{MAX_SECTIONS})")
            n_sections = MAX_SECTIONS

        # ---- Optional header ----
        opt_off = coff_off + 20
        opt_raw = src.read(opt_off, min(opt_size, 512))
        if len(opt_raw) < 2:
            messages.append("Optional header missing")
            root.add(Node("Optional Header", kind="error", offset=opt_off, size=0,
                          validation="error"))
            root.link_parents()
            return ParseResult(format_name="PE", file_size=src.size, root=root,
                               messages=messages)
        magic = struct.unpack("<H", opt_raw[0:2])[0]
        plus = magic == 0x20B
        if not plus and magic != 0x10B:
            messages.append(f"Unknown optional header magic 0x{magic:04X}")
        if len(opt_raw) < 70:
            root.add(Node("Optional Header", kind="error", offset=opt_off, size=len(opt_raw),
                          validation="error",
                          description=f"Optional header truncated ({len(opt_raw)} bytes, "
                                      f"need >= 70 for standard fields)"))
            messages.append("Optional header truncated")
            root.link_parents()
            return ParseResult(format_name="PE", file_size=src.size, root=root,
                               messages=messages)
        opt = Node("Optional Header (PE32+)" if plus else "Optional Header (PE32)",
                   kind="container", offset=opt_off, size=opt_size)
        root.add(opt)
        entry_rva = struct.unpack("<I", opt_raw[16:20])[0]
        image_base = (struct.unpack("<Q", opt_raw[24:32])[0] if plus
                      else struct.unpack("<I", opt_raw[28:32])[0])
        sect_align = struct.unpack("<I", opt_raw[32:36])[0]
        file_align = struct.unpack("<I", opt_raw[36:40])[0]
        subsystem = struct.unpack("<H", opt_raw[68:70])[0]
        opt.add(Node("Magic", kind="field", offset=opt_off, size=2,
                     value="PE32+" if plus else "PE32", data_type="uint16",
                     endian="little", raw=opt_raw[0:2],
                     description="64-bit" if plus else "32-bit image"))
        opt.add(Node("AddressOfEntryPoint", kind="field", offset=opt_off + 16, size=4,
                     value=f"RVA 0x{entry_rva:X}", data_type="uint32", endian="little",
                     raw=opt_raw[16:20], description="First code executed at startup"))
        opt.add(Node("ImageBase", kind="field",
                     offset=opt_off + (24 if plus else 28), size=8 if plus else 4,
                     value=f"0x{image_base:X}", data_type="uint64" if plus else "uint32",
                     endian="little",
                     raw=opt_raw[24:32] if plus else opt_raw[28:32]))
        opt.add(Node("SectionAlignment", kind="field", offset=opt_off + 32, size=4,
                     value=sect_align, data_type="uint32", endian="little",
                     raw=opt_raw[32:36]))
        opt.add(Node("FileAlignment", kind="field", offset=opt_off + 36, size=4,
                     value=file_align, data_type="uint32", endian="little",
                     raw=opt_raw[36:40]))
        opt.add(Node("Subsystem", kind="field", offset=opt_off + 68, size=2,
                     value=SUBSYSTEMS.get(subsystem, f"0x{subsystem:04X}"),
                     data_type="uint16", endian="little", raw=opt_raw[68:70]))

        # ---- Data directories ----
        dd_off = 112 if plus else 96
        n_dirs = 16
        dirs = []
        dd_node = Node("Data Directories", kind="container",
                       offset=opt_off + dd_off, size=n_dirs * 8,
                       description="Pointers to the important tables")
        opt.add(dd_node)
        for i in range(n_dirs):
            if dd_off + i * 8 + 8 > len(opt_raw):
                break
            va, size = struct.unpack("<II", opt_raw[dd_off + i * 8: dd_off + i * 8 + 8])
            dirs.append((va, size))
            if va or size:
                dd_node.add(Node(DIRECTORY_NAMES[i], kind="field",
                                 offset=opt_off + dd_off + i * 8, size=8,
                                 value=f"RVA 0x{va:X} ({size} bytes)",
                                 data_type="directory", endian="little"))
        if len(dirs) < n_dirs:
            messages.append(f"Only {len(dirs)} of {n_dirs} data directories present "
                            "(truncated optional header)")
        dirs.extend([(0, 0)] * (n_dirs - len(dirs)))

        # ---- Section table ----
        sect_off = opt_off + opt_size
        sections = []
        sect_node = Node("Section Table", kind="container", offset=sect_off,
                         size=40 * n_sections,
                         description=f"{n_sections} sections")
        root.add(sect_node)
        for i in range(n_sections):
            raw = src.read(sect_off + i * 40, 40)
            if len(raw) < 40:
                sect_node.add(Node("Truncated section entry", kind="error",
                                   offset=sect_off + i * 40, size=len(raw),
                                   validation="error"))
                messages.append("Section table truncated")
                break
            name_b = raw[0:8].rstrip(b"\x00")
            try:
                sname = name_b.decode("ascii")
            except UnicodeDecodeError:
                sname = name_b.hex()
            vsize, vaddr = struct.unpack("<II", raw[8:16])
            rsize, roff = struct.unpack("<II", raw[16:24])
            chars = struct.unpack("<I", raw[36:40])[0]
            sec = Node(sname or "(unnamed)", kind="container", offset=sect_off + i * 40,
                       size=40, description=f"Section {sname!r}")
            sec.add(Node("Name", kind="field", offset=sect_off + i * 40, size=8,
                         value=sname, data_type="string", raw=raw[0:8]))
            sec.add(Node("VirtualAddress", kind="field", offset=sect_off + i * 40 + 12,
                         size=4, value=f"RVA 0x{vaddr:X}", data_type="uint32",
                         endian="little", raw=raw[12:16]))
            sec.add(Node("VirtualSize", kind="field", offset=sect_off + i * 40 + 8,
                         size=4, value=vsize, data_type="uint32", endian="little",
                         raw=raw[8:12]))
            sec.add(Node("SizeOfRawData", kind="field", offset=sect_off + i * 40 + 16,
                         size=4, value=rsize, data_type="uint32", endian="little",
                         raw=raw[16:20]))
            sec.add(Node("PointerToRawData", kind="field", offset=sect_off + i * 40 + 20,
                         size=4, value=roff, data_type="uint32", endian="little",
                         raw=raw[20:24]))
            sec.add(Node("Characteristics", kind="field", offset=sect_off + i * 40 + 36,
                         size=4, value=_flags_str(chars), data_type="flags",
                         endian="little", raw=raw[36:40]))
            if roff and roff + rsize <= src.size:
                sec.add(Node("Raw data", kind="data", offset=roff, size=rsize,
                             description=f"{rsize} bytes at 0x{roff:X} "
                                         f"(RVA 0x{vaddr:X}, {_flags_str(chars)})"))
            if roff + rsize > src.size:
                sec.validation = "error"
                sec.add(Node("Out of bounds", kind="error", offset=roff, size=0,
                             validation="error",
                             description=f"Section data 0x{roff:X}+{rsize} exceeds "
                                         f"file size {src.size}"))
                messages.append(f"Section {sname!r} exceeds file boundary")
            sections.append({
                "name": sname, "vsize": vsize, "vaddr": vaddr,
                "rsize": rsize, "roff": roff, "chars": chars,
            })
            sect_node.add(sec)

        def rva_to_off(rva: int) -> int | None:
            for s in sections:
                span = max(s["vsize"], s["rsize"]) or s["rsize"]
                if s["vaddr"] <= rva < s["vaddr"] + span:
                    delta = rva - s["vaddr"]
                    if delta < s["rsize"]:
                        return s["roff"] + delta
                    return None
            if sections and rva < sections[0]["vaddr"]:
                return rva  # inside the headers
            return None

        # ---- imports ----
        if dirs[DIR_IMPORT][0]:
            imp = self._parse_imports(src, root, dirs[DIR_IMPORT], rva_to_off, plus)
            messages.extend(imp)
        # ---- exports ----
        if dirs[DIR_EXPORT][0]:
            exp = self._parse_exports(src, root, dirs[DIR_EXPORT], rva_to_off)
            messages.extend(exp)
        # ---- resources / relocs: show ranges ----
        for idx in (DIR_RESOURCE, DIR_RELOC, DIR_IAT):
            va, size = dirs[idx]
            if va or size:
                off = rva_to_off(va)
                root.add(Node(DIRECTORY_NAMES[idx], kind="data",
                              offset=off if off is not None else 0,
                              size=size if off is not None else 0,
                              description=f"RVA 0x{va:X}, {size} bytes"
                                          + ("" if off is not None else " (no raw mapping)")))

        # ---- validation: entry point ----
        ep_off = rva_to_off(entry_rva)
        if ep_off is None:
            messages.append(f"Entry point RVA 0x{entry_rva:X} does not map into any section")
        root.metadata["pe"].update({
            "entryPoint": entry_rva, "imageBase": image_base,
            "subsystem": SUBSYSTEMS.get(subsystem, subsystem),
            "sections": [{"name": s["name"], "vaddr": s["vaddr"],
                          "rawOff": s["roff"], "rawSize": s["rsize"],
                          "flags": _flags_str(s["chars"])} for s in sections],
        })
        root.link_parents()
        return ParseResult(format_name="PE", file_size=src.size, root=root,
                           messages=messages)

    def _parse_imports(self, src: DataSource, root: Node, dirent: tuple,
                       rva_to_off, plus: bool) -> list[str]:
        messages: list[str] = []
        va, _size = dirent
        node = Node("Import Table", kind="container",
                    description="DLLs this image depends on")
        root.add(node)
        base = rva_to_off(va)
        if base is None:
            node.add(Node("Unmapped RVA", kind="error", validation="error",
                          description=f"Import directory RVA 0x{va:X} not in any section"))
            messages.append("Import directory RVA unmapped")
            return messages
        dll_count = 0
        func_count = 0
        pos = base
        while dll_count < MAX_IMPORT_DLLS:
            desc = src.read(pos, 20)
            if len(desc) < 20:
                break
            oft, _ts, _fc, name_rva, ft = struct.unpack("<IIIII", desc)
            if oft == 0 and name_rva == 0 and ft == 0:
                break  # terminator
            name_off = rva_to_off(name_rva)
            dll_name = _read_cstr(src, name_off) if name_off is not None else "?"
            dll = Node(dll_name, kind="container", offset=pos, size=20,
                       description=f"Import descriptor for {dll_name!r}")
            dll.add(Node("Name RVA", kind="field", offset=pos + 12, size=4,
                         value=f"RVA 0x{name_rva:X}", data_type="uint32",
                         endian="little", raw=desc[12:16]))
            thunk_rva = oft or ft
            func_count += self._read_thunks(src, dll, thunk_rva, rva_to_off, plus)
            node.add(dll)
            dll_count += 1
            pos += 20
        if dll_count >= MAX_IMPORT_DLLS:
            messages.append("Import table hit safety cap — output truncated")
        node.description = f"{dll_count} DLLs, {func_count} functions"
        root.metadata["pe"]["imports"] = {"dlls": dll_count, "functions": func_count}
        return messages

    def _read_thunks(self, src: DataSource, dll: Node, thunk_rva: int,
                     rva_to_off, plus: bool) -> int:
        size = 8 if plus else 4
        ord_flag = 1 << 63 if plus else 1 << 31
        count = 0
        names = Node("Functions", kind="container",
                     description="Imported symbols (by name or ordinal)")
        dll.add(names)
        for i in range(MAX_IMPORT_FUNCS):
            off = rva_to_off(thunk_rva + i * size)
            if off is None:
                break
            raw = src.read(off, size)
            if len(raw) < size:
                break
            val = struct.unpack("<Q", raw)[0] if plus else struct.unpack("<I", raw)[0]
            if val == 0:
                break
            if val & ord_flag:
                ordinal = val & 0xFFFF
                names.add(Node(f"#{ordinal}", kind="field",
                               description="Imported by ordinal"))
            else:
                n_off = rva_to_off(val & 0x7FFFFFFF)
                fname = _read_cstr(src, n_off + 2) if n_off is not None else "?"
                names.add(Node(fname, kind="field", value=f"hint {_read_hint(src, n_off)}",
                               description="Imported by name"))
            count += 1
        if count >= MAX_IMPORT_FUNCS:
            names.add(Node("…", kind="info", description="function list truncated"))
        if count == 0:
            dll.add(Node("No named imports", kind="info"))
        return count

    def _parse_exports(self, src: DataSource, root: Node, dirent: tuple,
                       rva_to_off) -> list[str]:
        messages: list[str] = []
        va, size = dirent
        base = rva_to_off(va)
        node = Node("Export Table", kind="container",
                    offset=base if base is not None else 0,
                    size=size if base is not None else 0)
        root.add(node)
        if base is None:
            node.add(Node("Unmapped RVA", kind="error", validation="error",
                          description=f"Export directory RVA 0x{va:X} not in any section"))
            messages.append("Export directory RVA unmapped")
            return messages
        raw = src.read(base, 40)
        if len(raw) < 40:
            node.add(Node("Truncated", kind="error", validation="error"))
            return messages
        (_flags, _ts, _maj, _min, name_rva, _ordinal_base,
         n_funcs, n_names, _addr_funcs, addr_names, _) = struct.unpack("<IIHHIIIIIII", raw)
        dll_name = _read_cstr(src, rva_to_off(name_rva) or 0)
        node.add(Node("DLL name", kind="field", value=dll_name, data_type="string",
                      description=f"{n_funcs} functions, {n_names} exported by name"))
        names_node = Node("Exported Functions", kind="container",
                          description=f"{n_names} names (capped display)")
        node.add(names_node)
        shown = min(n_names, MAX_EXPORT_NAMES)
        for i in range(shown):
            p_off = rva_to_off(addr_names + i * 4)
            if p_off is None or p_off + 4 > src.size:
                break
            name_rva_i = struct.unpack("<I", src.read(p_off, 4))[0]
            fname = _read_cstr(src, rva_to_off(name_rva_i) or 0)
            names_node.add(Node(fname or f"#{i}", kind="field"))
        if n_names > shown:
            names_node.add(Node(f"… {n_names - shown} more", kind="info"))
        root.metadata["pe"]["exports"] = {"dllName": dll_name,
                                          "functions": n_funcs, "names": n_names}
        return messages


def _read_cstr(src: DataSource, off: int, cap: int = 512) -> str:
    if off is None or off < 0 or off >= src.size:
        return "?"
    raw = src.read(off, min(cap, src.size - off))
    i = raw.find(b"\x00")
    return raw[:i if i >= 0 else len(raw)].decode("utf-8", "replace")


def _read_hint(src: DataSource, off: int | None) -> int:
    if off is None:
        return 0
    raw = src.read(off, 2)
    return struct.unpack("<H", raw)[0] if len(raw) == 2 else 0


def u32_at(src: DataSource, off: int) -> int | None:
    raw = src.read(off, 4)
    return struct.unpack("<I", raw)[0] if len(raw) == 4 else None


def _coff_chars(v: int) -> str:
    names = []
    if v & 0x0001: names.append("RELOCS_STRIPPED")
    if v & 0x0002: names.append("EXECUTABLE_IMAGE")
    if v & 0x0020: names.append("LARGE_ADDRESS_AWARE")
    if v & 0x0100: names.append("32BIT_MACHINE")
    if v & 0x2000: names.append("DLL")
    return "|".join(names) or f"0x{v:04X}"
