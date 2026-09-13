"""PNG parser.

Parses the 8-byte signature plus every chunk. Known chunk types get field-
level decoding (IHDR is split into individual selectable fields). Unknown
chunks are kept gracefully with offset/length/CRC. All chunk CRCs are
verified. Malformed input never raises out of parse().
"""
from __future__ import annotations

import struct
import zlib

from ..core.datasource import DataSource
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

COLOR_TYPES = {
    0: "Grayscale",
    2: "Truecolor (RGB)",
    3: "Indexed (palette)",
    4: "Grayscale + Alpha",
    6: "Truecolor + Alpha (RGBA)",
}

INTERLACE = {0: "None (Adam7 off)", 1: "Adam7"}


def _crc_node(offset: int, type_name: str, data: bytes, stored_crc: int) -> Node:
    computed = zlib.crc32(type_name.encode("ascii") + data) & 0xFFFFFFFF
    if computed == stored_crc:
        return Node(
            name="CRC",
            kind="field",
            offset=offset,
            size=4,
            value=f"0x{stored_crc:08X} (valid)",
            data_type="uint32",
            endian="big",
            raw=struct.pack(">I", stored_crc),
            validation="ok",
        )
    return Node(
        name="CRC",
        kind="field",
        offset=offset,
        size=4,
        value=f"0x{stored_crc:08X} (mismatch, expected 0x{computed:08X})",
        data_type="uint32",
        endian="big",
        raw=struct.pack(">I", stored_crc),
        validation="error",
        description="CRC mismatch: chunk data may be corrupted",
    )


def _ihdr_children(off: int, data: bytes) -> list[Node]:
    b = data + b"\x00" * 13  # tolerate truncated IHDR without crashing
    fields: list[tuple[str, int, int, str, str, str]] = [
        ("Width", 4, 0, "uint32", "big", "Image width in pixels"),
        ("Height", 4, 4, "uint32", "big", "Image height in pixels"),
        ("Bit Depth", 1, 8, "uint8", "", "Bits per sample"),
        ("Color Type", 1, 9, "uint8", "", COLOR_TYPES.get(b[9], "Unknown")),
        ("Compression", 1, 10, "uint8", "", "0 = deflate"),
        ("Filter", 1, 11, "uint8", "", "0 = adaptive filtering"),
        ("Interlace", 1, 12, "uint8", "", INTERLACE.get(b[12], "Unknown")),
    ]
    nodes = []
    for name, size, rel, dtype, endian, desc in fields:
        raw = b[rel:rel + size]
        value: object
        if dtype == "uint32":
            value = int.from_bytes(raw, "big")
        else:
            value = raw[0] if raw else None
        nodes.append(Node(
            name=name, kind="field", offset=off + rel, size=size,
            value=value, description=desc, data_type=dtype, endian=endian, raw=raw,
        ))
    return nodes


def _decode_text_chunk(off: int, data: bytes) -> list[Node]:
    nodes = []
    # tEXt: keyword\0text   zTXt: keyword\0compression-method+zlib   iTXt: keyword\0lang\0translated\0text
    null = data.find(b"\x00")
    if null >= 0:
        key = data[:null]
        nodes.append(Node("Keyword", kind="field", offset=off, size=null,
                          value=key.decode("latin-1", "replace"), data_type="string"))
    return nodes


@register
class PNGParser(FormatParser):
    name = "PNG"
    magic = PNG_MAGIC

    def probe(self, src: DataSource) -> bool:
        return src.read(0, 8) == PNG_MAGIC

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="PNG", kind="container", offset=0, size=src.size,
                    description="Portable Network Graphics image")

        sig = src.read(0, 8)
        root.add(Node("Signature", kind="field", offset=0, size=8,
                      value=sig.hex(" "), data_type="magic", raw=sig,
                      description="\\x89PNG\\r\\n\\x1a\\n" if sig == PNG_MAGIC else "INVALID PNG signature"))

        pos = 8
        seen_ihdr = False
        seen_iend = False
        chunk_count = 0
        idat_count = 0
        idat_total = 0

        while pos + 8 <= src.size:
            header = src.read(pos, 8)
            if len(header) < 8:
                messages.append(f"Truncated chunk header at 0x{pos:X}")
                root.add(Node("Truncated chunk header", kind="error", offset=pos,
                              size=src.size - pos, validation="error",
                              description="Not enough bytes for length+type"))
                break
            length = int.from_bytes(header[0:4], "big")
            ctype = header[4:8]
            try:
                type_str = ctype.decode("ascii")
            except UnicodeDecodeError:
                type_str = ctype.hex()
            if not all(0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A for c in ctype):
                messages.append(f"Invalid chunk type bytes at 0x{pos + 4:X}: {ctype.hex(' ')}")
                root.add(Node(f"Invalid chunk type ({type_str})", kind="error",
                              offset=pos, size=min(8, src.size - pos), validation="error",
                              description="Chunk type contains non-alphabetic bytes"))
                break

            data_off = pos + 8
            crc_off = data_off + length
            # sanity: length must not exceed remaining file
            exceeds = crc_off + 4 > src.size
            data = src.read(data_off, length)
            crc_bytes = src.read(crc_off, 4)
            stored_crc = int.from_bytes(crc_bytes, "big") if len(crc_bytes) == 4 else -1

            chunk = Node(name=type_str, kind="container", offset=pos,
                         size=min(8 + length + 4, src.size - pos),
                         description=f"Chunk at 0x{pos:X}, data length {length}")
            chunk.add(Node("Length", kind="field", offset=pos, size=4,
                           value=length, data_type="uint32", endian="big",
                           raw=header[0:4], description="Data length in bytes"))
            chunk.add(Node("Type", kind="field", offset=pos + 4, size=4,
                           value=type_str, data_type="chunk-type", raw=ctype))

            flags = self._chunk_flags(ctype)
            if flags:
                chunk.metadata["flags"] = flags

            if exceeds:
                chunk.validation = "error"
                chunk.add(Node("Data", kind="error", offset=data_off,
                               size=src.size - data_off, validation="error",
                               description=f"Chunk length {length} exceeds file boundary "
                                           f"(only {src.size - data_off} bytes remain)"))
                messages.append(f"Chunk {type_str} at 0x{pos:X} exceeds file boundary")
                root.add(chunk)
                break

            data_node = Node("Data", kind="data", offset=data_off, size=length,
                             description=f"{length} bytes at 0x{data_off:X}")
            if type_str == "IHDR" and length == 13:
                seen_ihdr = True
                for f in _ihdr_children(data_off, data):
                    data_node.add(f)
            elif type_str in ("tEXt", "zTXt", "iTXt"):
                for f in _decode_text_chunk(data_off, data):
                    data_node.add(f)
                if type_str == "zTXt" and length > 2:
                    try:
                        text = zlib.decompress(data[data.find(b"\x00") + 2:]).decode("latin-1", "replace")
                        data_node.metadata["text"] = text
                    except zlib.error:
                        pass
                elif type_str == "tEXt" and length > 0:
                    null = data.find(b"\x00")
                    if null >= 0:
                        data_node.metadata["text"] = data[null + 1:].decode("latin-1", "replace")
            elif type_str == "gAMA" and length == 4:
                v = int.from_bytes(data, "big")
                data_node.add(Node("Gamma", kind="field", offset=data_off, size=4,
                                   value=v, data_type="uint32", endian="big", raw=data,
                                   description=f"Gamma = {v / 100000:.5f}"))
            elif type_str == "pHYs" and length == 9:
                x = int.from_bytes(data[0:4], "big")
                y = int.from_bytes(data[4:8], "big")
                unit = data[8]
                data_node.add(Node("Pixels per unit X", kind="field", offset=data_off, size=4,
                                   value=x, data_type="uint32", endian="big", raw=data[0:4]))
                data_node.add(Node("Pixels per unit Y", kind="field", offset=data_off + 4, size=4,
                                   value=y, data_type="uint32", endian="big", raw=data[4:8]))
                data_node.add(Node("Unit", kind="field", offset=data_off + 8, size=1,
                                   value="meter" if unit == 1 else str(unit), data_type="uint8",
                                   raw=data[8:9]))
            elif type_str == "sRGB" and length == 1:
                intents = {0: "Perceptual", 1: "Relative colorimetric",
                           2: "Saturation", 3: "Absolute colorimetric"}
                data_node.add(Node("Rendering intent", kind="field", offset=data_off, size=1,
                                   value=intents.get(data[0], str(data[0])), data_type="uint8",
                                   raw=data))
            elif type_str == "tIME" and length == 7:
                try:
                    y, mo, d, h, mi, s = struct.unpack(">HBBBBB", data)
                    data_node.add(Node("Last modification", kind="field", offset=data_off, size=7,
                                       value=f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}",
                                       data_type="timestamp", raw=data))
                except struct.error:
                    pass
            # iCCP/PLTE/IDAT/etc.: kept as raw data range
            chunk.add(data_node)

            if len(crc_bytes) == 4:
                chunk.add(_crc_node(crc_off, type_str, data, stored_crc))
            else:
                chunk.validation = "error"
                chunk.add(Node("CRC", kind="error", offset=crc_off,
                               size=max(0, src.size - crc_off), validation="error",
                               description="Missing/truncated CRC"))
                messages.append(f"Chunk {type_str} at 0x{pos:X} is truncated (missing CRC)")

            if type_str == "IDAT":
                idat_count += 1
                idat_total += length
            if type_str == "IEND":
                seen_iend = True
            root.add(chunk)
            chunk_count += 1
            pos = crc_off + 4

        if pos < src.size:
            trailing = src.size - pos
            root.add(Node("Trailing garbage", kind="error", offset=pos, size=trailing,
                          validation="error",
                          description=f"{trailing} unexpected bytes after last chunk"))
            messages.append(f"{trailing} trailing bytes after last chunk")

        if not seen_ihdr:
            messages.append("IHDR chunk missing or invalid")
            root.add(Node("IHDR missing", kind="error", offset=0, validation="error"))
        if not seen_iend:
            messages.append("IEND chunk missing (file may be truncated)")
            root.add(Node("IEND missing", kind="error", offset=src.size, validation="error"))

        root.metadata["image"] = self._image_summary(root)
        if idat_count:
            root.metadata["image"]["idatCount"] = idat_count
            root.metadata["image"]["idatTotal"] = idat_total

        root.link_parents()
        return ParseResult(format_name="PNG", file_size=src.size, root=root, messages=messages)

    @staticmethod
    def _chunk_flags(ctype: bytes) -> dict:
        if len(ctype) != 4:
            return {}
        c = list(ctype)
        return {
            "ancillary": bool(c[0] & 0x20),      # lowercase first letter
            "private": bool(c[1] & 0x20),
            "reservedBit": bool(c[2] & 0x20),
            "safeToCopy": bool(c[3] & 0x20),
        }

    @staticmethod
    def _image_summary(root: Node) -> dict:
        summary: dict = {}
        def find(node: Node):
            for c in node.children:
                if c.name == "IHDR":
                    d = next((x for x in c.children if x.name == "Data"), None)
                    if d:
                        vals = {x.name: x.value for x in d.children}
                        return vals
            return None
        vals = find(root)
        if vals:
            summary["width"] = vals.get("Width")
            summary["height"] = vals.get("Height")
            summary["bitDepth"] = vals.get("Bit Depth")
            summary["colorType"] = vals.get("Color Type")
            summary["colorTypeName"] = COLOR_TYPES.get(vals.get("Color Type"), "Unknown")
            summary["interlace"] = vals.get("Interlace")
        return summary
