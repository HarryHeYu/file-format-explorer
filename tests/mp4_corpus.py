"""Hand-craft a minimal, structurally valid MP4 (ftyp/moov/mdat)."""
from __future__ import annotations

import struct
from pathlib import Path


def box(btype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + btype + payload


def build_minimal_mp4() -> bytes:
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512)
               + b"isom" + b"iso2" + b"mp41")

    mvhd = box(b"mvhd", struct.pack(">IIIIII",
                0, 0, 0, 1000, 5000, 0x00010000)          # rate 1.0
               + b"\x00" * 10 + struct.pack(">iiiiii", 0, 0, 0, 0, 0, 0)
               + b"\x00" * 24 + struct.pack(">I", 3))      # next track id 3

    tkhd = box(b"tkhd", struct.pack(">IIIII", 0, 0, 0, 1, 0)   # track id 1
               + struct.pack(">I", 0)                          # duration 0 (in mv timescale placeholder)
               + b"\x00" * 8 + struct.pack(">hh", 0, 0)        # reserved, layer/alt
               + struct.pack(">h", 0) + b"\x00" * 2            # volume + reserved
               + struct.pack(">iiiiiiiii", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
               + struct.pack(">II", 640 << 16, 360 << 16))     # 640x360

    mdhd = box(b"mdhd", struct.pack(">IIII", 0, 0, 0, 900) + struct.pack(">I", 4500)
               + struct.pack(">hh", 0x55C4, 0))                # timescale 900, dur 4500 (5s)

    hdlr = box(b"hdlr", struct.pack(">I", 0) + b"\x00" * 4 + b"vide"
               + b"\x00" * 12 + b"VideoHandler\x00")

    smhd = box(b"smhd", struct.pack(">IHH", 0, 0, 0))
    entry = struct.pack(">I", 16) + b"mp4v" + b"\x00" * 6 + struct.pack(">HH", 1, 0)
    stsd = box(b"stsd", struct.pack(">II", 0, 1) + entry)
    stts = box(b"stts", struct.pack(">III", 0, 1, 225))
    stsz = box(b"stsz", struct.pack(">III", 0, 100, 4) + struct.pack(">I", 1024))
    stco = box(b"stco", struct.pack(">III", 0, 1, 1024))
    stbl = box(b"stbl", stsd + stts + stsz + stco)
    minf = box(b"minf", smhd + box(b"dinf", box(b"dref",
               struct.pack(">I", 1) + struct.pack(">I", 1) + b"url " + struct.pack(">I", 1))) + stbl)
    mdia = box(b"mdia", mdhd + hdlr + minf)
    trak = box(b"trak", tkhd + mdia)
    moov = box(b"moov", mvhd + trak)

    mdat_payload = bytes(1000)   # fake encoded media
    mdat = box(b"mdat", mdat_payload)
    free = box(b"free", b"")
    return ftyp + free + moov + mdat


def build_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    good = build_minimal_mp4()
    (out / "minimal.mp4").write_bytes(good)

    corrupt = out / "corrupt"
    corrupt.mkdir(exist_ok=True)
    # box size lies beyond EOF
    bad = bytearray(good)
    struct.pack_into(">I", bad, 0, 10 ** 7)
    (corrupt / "bad_size.mp4").write_bytes(bytes(bad))
    # truncated inside moov
    (corrupt / "truncated.mp4").write_bytes(good[: good.find(b"mdat") - 40])


if __name__ == "__main__":
    build_all(Path(__file__).resolve().parents[1] / "samples" / "mp4")
    print("mp4 corpus written")
