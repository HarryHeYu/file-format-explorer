"""MP4 parser (ISO base media file format box/atom hierarchy).

Walks the box tree (ftyp → moov{mvhd, trak{tkhd, mdia{...}}} → mdat …),
decoding mvhd (timescale/duration), tkhd (track id/dimensions), hdlr
(handler), mdhd and stsd (codec fourcc). Containers recurse, leaves keep
their byte range. Bounded depth and fan-out; malformed boxes become errors.
"""
from __future__ import annotations

import struct

from ..core.datasource import DataSource
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

CONTAINERS = {b"moov", b"trak", b"edts", b"mdia", b"minf", b"dinf", b"stbl",
              b"mvex", b"moof", b"traf", b"mfra", b"udta", b"ilst", b"skip"}
HANDLERS = {b"vide": "video track", b"soun": "audio track",
            b"hint": "hint track", b"meta": "metadata track"}
WELL_KNOWN = {
    b"ftyp": "File type", b"mdat": "Media data", b"free": "Free space",
    b"skip": "Free space", b"mvhd": "Movie header", b"tkhd": "Track header",
    b"mdhd": "Media header", b"hdlr": "Handler", b"smhd": "Sound media header",
    b"vmhd": "Video media header", b"stsd": "Sample description",
    b"stts": "Time-to-sample", b"stsc": "Sample-to-chunk", b"stsz": "Sample sizes",
    b"stco": "Chunk offsets", b"co64": "Chunk offsets (64-bit)",
    b"iods": "Initial object descriptor", b"dref": "Data reference",
    b"moov": "Movie container", b"trak": "Track container",
    b"mdia": "Media container", b"minf": "Media information",
    b"stbl": "Sample table", b"dinf": "Data information",
}
# safety caps
MAX_DEPTH = 12
MAX_BOXES_PER_LEVEL = 4096
MAX_TOTAL_BOXES = 200000


@register
class MP4Parser(FormatParser):
    name = "MP4"
    magic = b""  # probe: ftyp box within the first bytes

    def probe(self, src: DataSource) -> bool:
        head = src.read(0, 8)
        return len(head) == 8 and head[4:8] == b"ftyp"

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="MP4", kind="container", offset=0, size=src.size,
                    description="ISO base media file (MP4)")
        root.metadata["mp4"] = {"tracks": []}
        state = {"count": 0, "tracks": [], "brand": None,
                 "timescale": None, "duration": None}

        self._walk(src, root, 0, src.size, 0, messages, state)
        root.metadata["mp4"] = {"brand": state["brand"],
                                "timescale": state["timescale"],
                                "duration": state["duration"],
                                "tracks": state["tracks"]}
        root.link_parents()
        return ParseResult(format_name="MP4", file_size=src.size, root=root,
                           messages=messages)

    def _walk(self, src: DataSource, parent: Node, start: int, end: int,
              depth: int, messages: list, state: dict) -> None:
        if depth > MAX_DEPTH:
            messages.append("Box nesting exceeded safety depth")
            return
        pos = start
        n = 0
        while pos + 8 <= end:
            state["count"] += 1
            if state["count"] > MAX_TOTAL_BOXES:
                messages.append("Box count exceeded safety cap")
                return
            raw = src.read(pos, 8)
            size = struct.unpack(">I", raw[0:4])[0]
            btype = raw[4:8]
            header = 8
            if size == 1:  # 64-bit largesize
                big = src.read(pos + 8, 8)
                if len(big) < 8:
                    break
                size = struct.unpack(">Q", big)[0]
                header = 16
            elif size == 0:  # to EOF
                size = end - pos
            if size < header or pos + size > end:
                parent.add(Node(f"Bad box at 0x{pos:X}", kind="error", offset=pos,
                                size=max(0, min(8, end - pos)), validation="error",
                                description=f"type {btype!r}, size {size} invalid "
                                            f"(bounds {start}–{end})"))
                messages.append(f"Invalid box size for {btype!r} at 0x{pos:X}")
                return
            tstr = btype.decode("ascii", "replace")
            label = WELL_KNOWN.get(btype, tstr)
            node = Node(f"{tstr} — {label}" if btype not in WELL_KNOWN else label,
                        kind="container", offset=pos, size=size,
                        description=f"box {tstr!r}, {size} bytes at 0x{pos:X}")
            self._decode_box(src, node, btype, pos, header, size, state)
            if btype == b"trak":
                # aggregate one record per track: tkhd/hdlr/stsd all write into it
                state["current_track"] = {"id": None, "dims": None, "codec": None,
                                          "handler": None}
                state["tracks"].append(state["current_track"])
            if btype in CONTAINERS:
                self._walk(src, node, pos + header, pos + size, depth + 1,
                           messages, state)
            if btype == b"trak":
                state["current_track"] = None
            parent.add(node)
            pos += size
            n += 1
            if n >= MAX_BOXES_PER_LEVEL:
                messages.append("Too many boxes at one level — truncated")
                return
        if pos < end:
            parent.add(Node("Trailing bytes", kind="error", offset=pos,
                            size=end - pos, validation="error",
                            description=f"{end - pos} bytes not covered by a box"))

    def _decode_box(self, src: DataSource, node: Node, btype: bytes,
                    pos: int, header: int, size: int, state: dict) -> None:
        body = pos + header
        if btype == b"ftyp":
            raw = src.read(body, min(size - header, 32))
            brand = raw[0:4].decode("ascii", "replace")
            node.add(Node("Major brand", kind="field", offset=body, size=4,
                          value=brand, data_type="fourcc", raw=raw[0:4]))
            if len(raw) >= 8:
                node.add(Node("Minor version", kind="field", offset=body + 4, size=4,
                              value=struct.unpack(">I", raw[4:8])[0],
                              data_type="uint32", endian="big", raw=raw[4:8]))
            compat = [raw[i:i + 4].decode("ascii", "replace")
                      for i in range(8, len(raw) - 3, 4)]
            if compat:
                node.add(Node("Compatible brands", kind="field", value=", ".join(compat),
                              data_type="fourcc[]"))
            state["brand"] = brand
        elif btype == b"mvhd":
            raw = src.read(body, min(size - header, 32))
            if len(raw) >= 20:
                version = raw[0]
                if version == 1 and len(raw) >= 32:
                    timescale = struct.unpack(">I", raw[20:24])[0]
                    duration = struct.unpack(">Q", raw[24:32])[0]
                    t_off = body + 20
                else:
                    timescale = struct.unpack(">I", raw[12:16])[0]
                    duration = struct.unpack(">I", raw[16:20])[0]
                    t_off = body + 12
                node.add(Node("Timescale", kind="field", offset=t_off, size=4,
                              value=timescale, data_type="uint32", endian="big"))
                node.add(Node("Duration", kind="field",
                              offset=t_off + 4, size=8 if version == 1 else 4,
                              value=duration, data_type="uint64" if version == 1 else "uint32",
                              endian="big",
                              description=f"{duration / timescale:.3f} s"
                                          if timescale else ""))
                state["timescale"] = timescale
                state["duration"] = duration
        elif btype == b"tkhd":
            raw = src.read(body, min(size - header, 96))
            version = raw[0] if raw else 0
            # ver/flags(4) + creation/modification (4 or 8 each) → track_ID
            base = 12 if version == 0 else 20
            if len(raw) >= base + 4:
                track_id = struct.unpack(">I", raw[base:base + 4])[0]
                node.add(Node("Track ID", kind="field", offset=body + base, size=4,
                              value=track_id, data_type="uint32", endian="big"))
                # width/height are the last 8 bytes (16.16 fixed), after the 36-byte matrix
                dims = None
                if len(raw) >= base + 64 + 8:
                    w_off = body + base + 64
                    w, h = struct.unpack(">II", raw[base + 64:base + 72])
                    dims = ((w >> 16) + (w & 0xFFFF) / 65536,
                            (h >> 16) + (h & 0xFFFF) / 65536)
                    node.add(Node("Dimensions", kind="field",
                                  offset=w_off, size=8,
                                  value=f"{dims[0]:g} × {dims[1]:g}",
                                  data_type="16.16 fixed",
                                  description="width × height (tkhd fixed point)"))
                if state.get("current_track") is not None:
                    state["current_track"]["id"] = track_id
                    state["current_track"]["dims"] = dims
        elif btype == b"hdlr":
            raw = src.read(body, min(size - header, 24))
            if len(raw) >= 12:
                handler = raw[8:12]
                node.add(Node("Handler", kind="field", offset=body + 8, size=4,
                              value=handler.decode("ascii", "replace"),
                              data_type="fourcc", raw=raw[8:12],
                              description=HANDLERS.get(handler, "unknown")))
                if state.get("current_track") is not None:
                    state["current_track"]["handler"] = handler.decode("ascii", "replace")
        elif btype == b"mdhd":
            raw = src.read(body, min(size - header, 32))
            version = raw[0] if raw else 0
            if version == 1 and len(raw) >= 28:
                timescale = struct.unpack(">I", raw[20:24])[0]
            elif len(raw) >= 16:
                timescale = struct.unpack(">I", raw[12:16])[0]
            else:
                timescale = 0
            ts_off = body + (20 if version == 1 else 12)
            node.add(Node("Media timescale", kind="field", offset=ts_off, size=4,
                          value=timescale, data_type="uint32", endian="big",
                          raw=raw[20:24] if (version == 1 and len(raw) >= 24) else
                              (raw[12:16] if len(raw) >= 16 else b""),
                          description=f"{timescale} units per second"))
        elif btype == b"stsd":
            raw = src.read(body, min(size - header, 24))
            if len(raw) >= 16:
                codec = raw[12:16]
                node.add(Node("Codec", kind="field", offset=body + 12, size=4,
                              value=codec.decode("ascii", "replace"),
                              data_type="fourcc", raw=codec,
                              description="sample entry fourcc (avc1/mp4a/…)"))
                if state.get("current_track") is not None:
                    state["current_track"]["codec"] = codec.decode("ascii", "replace")
        elif btype == b"mdat":
            node.add(Node("Media payload", kind="data", offset=body,
                          size=max(0, size - header),
                          description=f"{size - header} bytes of encoded media"))
