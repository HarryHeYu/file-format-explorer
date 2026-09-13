"""Generate minimal but structurally complete ELF64 binaries by hand.

Layout is packed sequentially with explicit alignment so every header
offset is guaranteed self-consistent.
"""
from __future__ import annotations

import struct
from pathlib import Path

ELF_MAGIC = b"\x7fELF"


def build_elf64() -> bytes:
    text = b"\x90" * 32
    data = b"hello elf\x00"

    def align(n: int, a: int = 8) -> int:
        return (n + a - 1) & ~(a - 1)

    # sequential layout, each piece aligned to 8
    off_ehdr = 0
    off_phdrs = off_ehdr + 64
    off_text = align(off_phdrs + 2 * 56)
    off_data = off_text + len(text)
    off_symtab = align(off_data + len(data))
    symtab = (struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0)
              + struct.pack("<IBBHQQ", 1, 0x12, 0, 1, off_text, 32))  # strtab+1 = "main"
    off_shstrtab = align(off_symtab + len(symtab))
    shstrtab = b"\x00.text\x00.data\x00.shstrtab\x00.symtab\x00.strtab\x00"
    off_strtab = align(off_shstrtab + len(shstrtab))
    strtab = b"\x00main\x00my_var\x00"
    off_shdrs = align(off_strtab + len(strtab))

    def str_off(s: str, tab: bytes) -> int:
        return tab.find(s.encode() + b"\x00")

    ehdr = struct.pack(
        "<16sHHIQQQIHHHHHH",
        ELF_MAGIC + bytes([2, 1, 1, 0]) + b"\x00" * 8,
        2, 62, 1,                 # ET_EXEC, EM_X86_64, version
        off_text,                 # e_entry
        off_phdrs, off_shdrs, 0,
        64, 56, 2, 64, 6, 3,      # ehsize, phentsize, phnum=2, shentsize=64, shnum=6, shstrndx=3
    )
    phdrs = b"".join([
        struct.pack("<IIQQQQQQ", 1, 5, off_text, 0x400000 + off_text,
                    0x400000 + off_text, len(text), len(text), 0x1000),
        struct.pack("<IIQQQQQQ", 1, 6, off_data, 0x400000 + off_data,
                    0x400000 + off_data, len(data), len(data) + 8, 0x1000),
    ])

    def shdr(name_off, typ, flags, addr, off, size, link=0, info=0, entsize=0):
        return struct.pack("<IIQQQQIIQQ", name_off, typ, flags, addr, off,
                           size, link, info, 16, entsize)

    shdrs = b"".join([
        shdr(0, 0, 0, 0, 0, 0),
        shdr(str_off(".text", shstrtab), 1, 0x6, 0x400000 + off_text, off_text, len(text)),
        shdr(str_off(".data", shstrtab), 1, 0x3, 0x400000 + off_data, off_data, len(data)),
        shdr(str_off(".shstrtab", shstrtab), 3, 0, 0, off_shstrtab, len(shstrtab)),
        shdr(str_off(".symtab", shstrtab), 2, 0, 0, off_symtab, len(symtab),
             link=5, info=1, entsize=24),
        shdr(str_off(".strtab", shstrtab), 3, 0, 0, off_strtab, len(strtab)),
    ])

    buf = bytearray(off_shdrs + len(shdrs))
    buf[off_ehdr:off_ehdr + 64] = ehdr
    buf[off_phdrs:off_phdrs + len(phdrs)] = phdrs
    buf[off_text:off_text + len(text)] = text
    buf[off_data:off_data + len(data)] = data
    buf[off_symtab:off_symtab + len(symtab)] = symtab
    buf[off_shstrtab:off_shstrtab + len(shstrtab)] = shstrtab
    buf[off_strtab:off_strtab + len(strtab)] = strtab
    buf[off_shdrs:off_shdrs + len(shdrs)] = shdrs
    return bytes(buf)


def build_elf32() -> bytes:
    """Minimal ELF32 x86 executable: 1 phdr, 3 sections, exercising the
    13-field 32-bit ehdr and 40-byte shdr paths."""
    text = b"\x90" * 16
    shstrtab = b"\x00.text\x00.shstrtab\x00"

    def align(n, a=4):
        return (n + a - 1) & ~(a - 1)

    off_ehdr, off_phdrs = 0, 52
    off_text = align(off_phdrs + 32)
    off_shstrtab = align(off_text + len(text))
    off_shdrs = align(off_shstrtab + len(shstrtab))

    ehdr = struct.pack("<16sHHIIIIIHHHHHH",
                       b"\x7fELF" + bytes([1, 1, 1, 0]) + b"\x00" * 8,
                       2, 3, 1,                 # ET_EXEC, EM_386
                       off_text, off_phdrs, off_shdrs, 0,
                       52, 32, 1, 40, 3, 2)     # phnum=1, shnum=3, shstrndx=2
    phdr = struct.pack("<IIIIIIII", 1, off_text, 0x1000, 0x1000,
                       len(text), len(text), 5, 16)

    def shdr(name_off, typ, flags, addr, off, size):
        return struct.pack("<IIIIIIIIII", name_off, typ, flags, addr, off,
                           size, 0, 0, 16, 0)

    def str_off(s, tab):
        return tab.find(s.encode() + b"\x00")

    shdrs = (shdr(0, 0, 0, 0, 0, 0)
             + shdr(str_off(".text", shstrtab), 1, 0x6, 0x1000, off_text, len(text))
             + shdr(str_off(".shstrtab", shstrtab), 3, 0, 0, off_shstrtab, len(shstrtab)))

    buf = bytearray(off_shdrs + len(shdrs))
    buf[0:52] = ehdr
    buf[off_phdrs:off_phdrs + 32] = phdr
    buf[off_text:off_text + len(text)] = text
    buf[off_shstrtab:off_shstrtab + len(shstrtab)] = shstrtab
    buf[off_shdrs:off_shdrs + len(shdrs)] = shdrs
    return bytes(buf)


def build_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "minimal64.elf").write_bytes(build_elf64())
    (out / "minimal32.elf").write_bytes(build_elf32())

    corrupt = out / "corrupt"
    corrupt.mkdir(exist_ok=True)
    good = build_elf64()
    bad = bytearray(good); bad[0] = 0x7E
    (corrupt / "bad_magic.elf").write_bytes(bytes(bad))
    (corrupt / "truncated.elf").write_bytes(good[:200])
    bad2 = bytearray(good)
    struct.pack_into("<Q", bad2, 40, 1 << 40)   # e_shoff beyond EOF
    (corrupt / "bad_shoff.elf").write_bytes(bytes(bad2))


if __name__ == "__main__":
    build_all(Path(__file__).resolve().parents[1] / "samples" / "elf")
    print("elf corpus written")
