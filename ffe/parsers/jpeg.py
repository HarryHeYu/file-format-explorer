"""JPEG parser (marker/segment traversal).

Walks SOI → segments → SOS (entropy-coded scan skipped) → EOI.
Field-level decoding for SOF (dimensions, components), DQT (table summary),
APP0 (JFIF), APP1 (EXIF presence). Malformed input never raises.
"""
from __future__ import annotations

import struct

from ..core.datasource import DataSource
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

MARKER_NAMES = {
    0xC0: "SOF0 (Baseline DCT)", 0xC1: "SOF1", 0xC2: "SOF2 (Progressive)",
    0xC3: "SOF3 (Lossless)", 0xC4: "DHT (Huffman table)", 0xC5: "SOF5",
    0xC6: "SOF6", 0xC7: "SOF7", 0xC8: "JPG", 0xC9: "SOF9", 0xCA: "SOF10",
    0xCB: "SOF11", 0xCC: "DAC", 0xCD: "SOF13", 0xCE: "SOF14", 0xCF: "SOF15",
    0xD0: "RST0", 0xD1: "RST1", 0xD2: "RST2", 0xD3: "RST3",
    0xD4: "RST4", 0xD5: "RST5", 0xD6: "RST6", 0xD7: "RST7",
    0xD8: "SOI", 0xD9: "EOI", 0xDA: "SOS", 0xDB: "DQT",
    0xDC: "DNL", 0xDD: "DRI", 0xDE: "DHP", 0xDF: "EXP",
    0xE0: "APP0", 0xE1: "APP1", 0xE2: "APP2", 0xE3: "APP3", 0xE4: "APP4",
    0xE5: "APP5", 0xE6: "APP6", 0xE7: "APP7", 0xE8: "APP8", 0xE9: "APP9",
    0xEA: "APP10", 0xEB: "APP11", 0xEC: "APP12", 0xED: "APP13",
    0xEE: "APP14", 0xEF: "APP15",
    0xF0: "JPG0", 0xF1: "JPG1", 0xFD: "JPG13", 0xFE: "COM (comment)",
}
NO_LENGTH = {0xD8, 0x01} | set(range(0xD0, 0xD8))  # SOI, TEM, RSTn


def _marker_name(b: int) -> str:
    return MARKER_NAMES.get(b, f"RESERVED 0xFF{b:02X}")


@register
class JPEGParser(FormatParser):
    name = "JPEG"
    magic = b"\xFF\xD8\xFF"

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="JPEG", kind="container", offset=0, size=src.size,
                    description="JPEG (JFIF/EXIF) still image")

        soi = src.read(0, 2)
        root.add(Node("SOI", kind="field", offset=0, size=2, value="FFD8",
                      data_type="marker", raw=soi, description="Start of image"))

        pos = 2
        seen_eoi = False
        sof_info: dict = {}
        seg_count = 0
        while pos < src.size:
            # entropy-coded scan: skip to EOI (marker fill bytes 00 / FF padding)
            head = src.read(pos, 2)
            if len(head) < 2:
                messages.append("Truncated data before EOI")
                root.add(Node("Truncated", kind="error", offset=pos,
                              size=src.size - pos, validation="error",
                              description="Ran out of bytes before EOI"))
                break
            if head[0] != 0xFF:
                messages.append(f"Lost marker sync at 0x{pos:X} (expected 0xFF, got 0x{head[0]:02X})")
                root.add(Node("Lost marker sync", kind="error", offset=pos,
                              size=src.size - pos, validation="error",
                              description=f"Expected 0xFF marker prefix, got 0x{head[0]:02X}"))
                break
            marker = head[1]
            if marker == 0xFF:  # fill bytes
                pos += 1
                continue
            if marker == 0xD9:  # EOI
                root.add(Node("EOI", kind="field", offset=pos, size=2, value="FFD9",
                              data_type="marker", raw=head, description="End of image"))
                seen_eoi = True
                pos += 2
                break

            name = _marker_name(marker)
            if marker in NO_LENGTH:
                seg = Node(name, kind="field", offset=pos, size=2,
                           value=f"FF{marker:02X}", data_type="marker", raw=head)
                root.add(seg)
                pos += 2
                continue

            len_bytes = src.read(pos + 2, 2)
            if len(len_bytes) < 2:
                messages.append(f"Truncated {name} at 0x{pos:X}")
                root.add(Node(f"{name} (truncated)", kind="error", offset=pos,
                              size=src.size - pos, validation="error"))
                break
            seg_len = struct.unpack(">H", len_bytes)[0]
            total = 2 + seg_len
            exceeds = pos + total > src.size

            seg = Node(name, kind="container", offset=pos,
                       size=min(total, src.size - pos),
                       description=f"{name} segment at 0x{pos:X}, length {seg_len}")
            seg.add(Node("Marker", kind="field", offset=pos, size=2,
                         value=f"FF{marker:02X}", data_type="marker", raw=head))
            seg.add(Node("Length", kind="field", offset=pos + 2, size=2,
                         value=seg_len, data_type="uint16", endian="big",
                         raw=len_bytes, description="Includes the 2 length bytes"))
            data_off = pos + 4
            data_len = max(0, seg_len - 2)

            if exceeds:
                seg.validation = "error"
                seg.add(Node("Payload", kind="error", offset=data_off,
                             size=max(0, src.size - data_off), validation="error",
                             description=f"Segment length {seg_len} exceeds file boundary"))
                messages.append(f"{name} at 0x{pos:X} exceeds file boundary")
                root.add(seg)
                break

            payload = src.read(data_off, data_len)
            data_node = Node("Payload", kind="data", offset=data_off, size=data_len,
                             description=f"{data_len} bytes at 0x{data_off:X}")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF) and len(payload) >= 6:
                sof_info = self._sof_fields(data_node, data_off, payload)
            elif marker == 0xDB and len(payload) >= 1:
                self._dqt_summary(data_node, payload, data_off)
            elif marker == 0xE0 and payload[:4] == b"JFIF":
                self._jfif_fields(data_node, data_off, payload)
            elif marker == 0xE1 and payload[:6] == b"Exif\x00\x00":
                data_node.add(Node("Header", kind="field", offset=data_off, size=6,
                                   value="Exif\\0\\0", data_type="string",
                                   description="EXIF metadata present (TIFF structure not parsed yet)"))
            elif marker == 0xDD and len(payload) >= 4:
                data_node.add(Node("Restart interval", kind="field", offset=data_off, size=2,
                                   value=struct.unpack(">H", payload[:2])[0],
                                   data_type="uint16", endian="big", raw=payload[:2]))
            seg.add(data_node)
            root.add(seg)
            seg_count += 1
            pos += total

            if marker == 0xDA:  # SOS: skip entropy-coded scan to next real marker
                scan_end = self._skip_entropy(src, pos)
                if scan_end > pos:
                    root.add(Node("Entropy-coded scan", kind="data", offset=pos,
                                  size=scan_end - pos,
                                  description=f"Compressed image data ({scan_end - pos} bytes)"))
                pos = scan_end

        if not seen_eoi:
            messages.append("EOI marker missing (file may be truncated)")
            root.add(Node("EOI missing", kind="error", offset=src.size, validation="error"))
        if not sof_info:
            messages.append("No SOF segment found (dimensions unknown)")

        root.metadata["image"] = sof_info
        root.metadata["segments"] = seg_count
        root.link_parents()
        return ParseResult(format_name="JPEG", file_size=src.size, root=root, messages=messages)

    @staticmethod
    def _skip_entropy(src: DataSource, pos: int) -> int:
        """Skip entropy-coded scan data after SOS.

        Inside the scan, 0xFF 0x00 is a stuffed literal, 0xFF D0-D7 are
        restart markers, and 0xFF 0xFF is padding. Any other 0xFF pair
        starts the next segment. Returns the offset of that segment, or
        EOF (the main loop will report missing EOI).
        """
        window = 1 << 16
        search = pos
        carry = b""   # last byte(s) not yet classified, may start with 0xFF
        while True:
            chunk = src.read(search, window)
            if not chunk:
                return src.size
            buf = carry + chunk
            base = search - len(carry)
            i = 0
            while i < len(buf) - 1:
                if buf[i] != 0xFF:
                    i += 1
                    continue
                b = buf[i + 1]
                if b == 0x00 or 0xD0 <= b <= 0xD7:
                    i += 2
                elif b == 0xFF:
                    i += 1
                else:
                    return base + i
            if len(chunk) < window:
                return src.size  # EOF without a following marker
            # keep the final byte: it may pair with the next window's first byte
            carry = buf[-1:]
            search = base + len(buf) - 1

    @staticmethod
    def _sof_fields(data_node: Node, off: int, payload: bytes) -> dict:
        precision, height, width, ncomp = struct.unpack(">BHHB", payload[:6])
        data_node.add(Node("Precision", kind="field", offset=off, size=1,
                           value=precision, data_type="uint8", raw=payload[0:1],
                           description="bits per sample (usually 8)"))
        data_node.add(Node("Height", kind="field", offset=off + 1, size=2,
                           value=height, data_type="uint16", endian="big", raw=payload[1:3]))
        data_node.add(Node("Width", kind="field", offset=off + 3, size=2,
                           value=width, data_type="uint16", endian="big", raw=payload[3:5]))
        data_node.add(Node("Components", kind="field", offset=off + 5, size=1,
                           value=ncomp, data_type="uint8", raw=payload[5:6],
                           description="1=grayscale 3=YCbCr 4=CMYK"))
        return {"width": width, "height": height, "precision": precision,
                "components": ncomp}

    @staticmethod
    def _dqt_summary(data_node: Node, payload: bytes, data_off: int = 0) -> None:
        # walk quantization tables: Pq(1 bit)+Tq(7 bits) then 64 values
        i = 0
        table_no = 0
        while i < len(payload):
            pqtq = payload[i]
            precision = (pqtq >> 4) & 1
            table_id = pqtq & 0x0F
            vlen = 64 * (2 if precision else 1)
            if i + 1 + vlen > len(payload):
                data_node.add(Node(f"Table {table_id}", kind="error", offset=data_off + i,
                                   validation="error",
                                   description="Truncated quantization table"))
                break
            data_node.add(Node(f"Table {table_id}", kind="field",
                               offset=data_off + i, size=1 + vlen,
                               value=f"id={table_id}, {'16-bit' if precision else '8-bit'}, 64 entries",
                               data_type="table"))
            i += 1 + vlen
            table_no += 1

    @staticmethod
    def _jfif_fields(data_node: Node, off: int, payload: bytes) -> None:
        if len(payload) < 14:
            return
        major, minor = payload[5], payload[6]
        units = payload[7]
        xd, yd = struct.unpack(">HH", payload[8:12])
        unit_name = {0: "aspect ratio only", 1: "dots per inch", 2: "dots per cm"}.get(units, str(units))
        data_node.add(Node("JFIF version", kind="field", offset=off + 5, size=2,
                           value=f"{major}.{minor}", data_type="version", raw=payload[5:7]))
        data_node.add(Node("Density unit", kind="field", offset=off + 7, size=1,
                           value=unit_name, data_type="uint8", raw=payload[7:8]))
        data_node.add(Node("X density", kind="field", offset=off + 8, size=2,
                           value=xd, data_type="uint16", endian="big", raw=payload[8:10]))
        data_node.add(Node("Y density", kind="field", offset=off + 10, size=2,
                           value=yd, data_type="uint16", endian="big", raw=payload[10:12]))
