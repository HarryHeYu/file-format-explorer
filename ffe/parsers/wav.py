"""WAV parser (RIFF/WAVE container).

Parses the RIFF header and every sub-chunk (fmt / data / LIST / fact / ...).
Field-level decoding for `fmt ` (codec, channels, sample rate, byte rate,
bits per sample) and computed duration. Malformed input never raises.
"""
from __future__ import annotations

import struct

from ..core.datasource import DataSource, u32le
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

CODECS = {
    0x0001: "PCM (uncompressed)",
    0x0002: "Microsoft ADPCM",
    0x0003: "IEEE float",
    0x0006: "ITU G.711 a-law",
    0x0007: "ITU G.711 mu-law",
    0x0011: "IMA ADPCM",
    0x0055: "MPEG Layer 3",
    0xFFFE: "WAVE_FORMAT_EXTENSIBLE",
}


@register
class WAVParser(FormatParser):
    name = "WAV"
    magic = b""  # probe() checks RIFF + WAVE at offset 8

    def probe(self, src: DataSource) -> bool:
        head = src.read(0, 12)
        return len(head) == 12 and head[0:4] == b"RIFF" and head[8:12] == b"WAVE"

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="WAV", kind="container", offset=0, size=src.size,
                    description="RIFF Waveform Audio")

        header = src.read(0, 12)
        riff_size = u32le(header, 4)
        declared = riff_size + 8
        root.add(Node("RIFF magic", kind="field", offset=0, size=4,
                      value="RIFF", data_type="magic", raw=header[0:4]))
        root.add(Node("RIFF size", kind="field", offset=4, size=4,
                      value=riff_size, data_type="uint32", endian="little", raw=header[4:8],
                      description=f"Payload size; file should be {declared} bytes"
                                  + ("" if declared == src.size else f" (actual {src.size})")))
        if declared != src.size:
            if declared < src.size:
                messages.append(f"File has {src.size - declared} trailing bytes beyond RIFF size")
            else:
                messages.append(f"RIFF size declares {declared} bytes but file is truncated at {src.size}")
        root.add(Node("Form type", kind="field", offset=8, size=4,
                      value=header[8:12].decode("ascii", "replace"), data_type="fourcc",
                      raw=header[8:12]))

        fmt_info: dict = {}
        data_info: dict = {}
        pos = 12
        while pos + 8 <= src.size:
            head = src.read(pos, 8)
            if len(head) < 8:
                messages.append(f"Truncated chunk header at 0x{pos:X}")
                root.add(Node("Truncated chunk header", kind="error", offset=pos,
                              size=src.size - pos, validation="error"))
                break
            cid = head[0:4].decode("ascii", "replace")
            length = u32le(head, 4)
            data_off = pos + 8
            exceeds = data_off + length > src.size
            data = src.read(data_off, length)

            chunk = Node(name=cid, kind="container", offset=pos,
                         size=min(8 + length, src.size - pos),
                         description=f"Sub-chunk at 0x{pos:X}, data length {length}")
            chunk.add(Node("Chunk id", kind="field", offset=pos, size=4,
                           value=cid, data_type="fourcc", raw=head[0:4]))
            chunk.add(Node("Length", kind="field", offset=pos + 4, size=4,
                           value=length, data_type="uint32", endian="little", raw=head[4:8]))

            if exceeds:
                if cid == "data":
                    data_info = {"offset": data_off, "size": max(0, src.size - data_off)}
                chunk.validation = "error"
                chunk.add(Node("Data", kind="error", offset=data_off,
                               size=max(0, src.size - data_off), validation="error",
                               description=f"Chunk length {length} exceeds file boundary "
                                           f"(only {src.size - data_off} bytes remain)"))
                messages.append(f"Chunk {cid} at 0x{pos:X} exceeds file boundary")
                root.add(chunk)
                break

            data_node = Node("Data", kind="data", offset=data_off, size=length,
                             description=f"{length} bytes at 0x{data_off:X}")
            if cid == "fmt " and length >= 16:
                fmt_info = self._fmt_fields(data_node, data_off, data, messages)
            elif cid == "data":
                data_info = {"offset": data_off, "size": length}
            elif cid == "fact" and length >= 4:
                frames = int.from_bytes(data[0:4], "little")
                data_node.add(Node("Sample length (frames)", kind="field",
                                   offset=data_off, size=4, value=frames,
                                   data_type="uint32", endian="little", raw=data[0:4]))
            chunk.add(data_node)
            root.add(chunk)
            # odd-sized RIFF chunks are pad-byte aligned; tolerate a missing pad at EOF
            pos = data_off + length + (length & 1)

        if not fmt_info:
            messages.append("fmt chunk missing or too short")
            root.add(Node("fmt missing", kind="error", offset=0, validation="error"))
        if not data_info:
            messages.append("data chunk missing")
            root.add(Node("data missing", kind="error", offset=0, validation="error"))
        else:
            root.metadata["audio"] = {**fmt_info, **data_info,
                                      **self._duration(fmt_info, data_info)}

        root.link_parents()
        return ParseResult(format_name="WAV", file_size=src.size, root=root, messages=messages)

    @staticmethod
    def _fmt_fields(data_node: Node, off: int, data: bytes, messages: list) -> dict:
        fmt = struct.unpack("<HHIIHH", data[:16])
        codec, channels, rate, byte_rate, block_align, bits = fmt
        codec_name = CODECS.get(codec, f"0x{codec:04X}")
        # (name, value, rel_offset, size, description) — fmt layout is not uniform-width
        fields = [
            ("Audio format", codec, 0, 2, f"{codec_name}"),
            ("Channels", channels, 2, 2, "mono" if channels == 1 else f"{channels} channels"),
            ("Sample rate", rate, 4, 4, f"{rate} Hz"),
            ("Byte rate", byte_rate, 8, 4, f"{byte_rate} B/s (= rate × block align)"),
            ("Block align", block_align, 12, 2, "bytes per sample frame"),
            ("Bits per sample", bits, 14, 2, f"{bits // max(1, channels)} bit/sample × {channels}"),
        ]
        for name, value, rel, size, desc in fields:
            data_node.add(Node(name, kind="field", offset=off + rel, size=size,
                               value=value, data_type="uint16" if size == 2 else "uint32",
                               endian="little", raw=data[rel:rel + size], description=desc))
        if len(data) > 16:
            data_node.add(Node("Extension", kind="field", offset=off + 16,
                               size=len(data) - 16, data_type="raw",
                               description=f"{len(data) - 16} extension bytes"))
        if block_align and byte_rate != rate * block_align:
            messages.append(f"Byte rate {byte_rate} != sample rate × block align ({rate * block_align})")
        return {"codec": codec_name, "channels": channels, "sampleRate": rate,
                "byteRate": byte_rate, "blockAlign": block_align, "bitsPerSample": bits}

    @staticmethod
    def _duration(fmt: dict, data: dict) -> dict:
        out: dict = {}
        if fmt.get("byteRate"):
            secs = data["size"] / fmt["byteRate"]
            out["durationSec"] = round(secs, 3)
            mins, secs = divmod(secs, 60)
            out["duration"] = f"{int(mins)}:{secs:04.1f}"
        return out
