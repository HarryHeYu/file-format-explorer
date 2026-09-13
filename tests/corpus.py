"""Generate a PNG test corpus without external dependencies."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIG = b"\x89PNG\r\n\x1a\n"


def chunk(ctype: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def ihdr(w: int, h: int, depth=8, color=6, interlace=0) -> bytes:
    return chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, color, 0, 0, interlace))


def encode_rows(rows: list[bytes], h: int) -> bytes:
    raw = b"".join(b"\x00" + r for r in rows)
    return zlib.compress(raw, 6)


def save(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def solid_rgba(w: int, h: int, rgba=(200, 60, 30, 255)) -> bytes:
    return encode_rows([bytes(rgba) * w] * h, h)


def gradient_rgba(w: int, h: int) -> bytes:
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            row += bytes(((x * 255 // max(1, w - 1)), (y * 255 // max(1, h - 1)), 128, 255))
        rows.append(bytes(row))
    return encode_rows(rows, h)


def make_png(w, h, idat, extra_chunks=()) -> bytes:
    body = SIG + ihdr(w, h)
    for c in extra_chunks:
        body += c
    body += chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return body


def build_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    # minimal 1x1
    save(out / "minimal.png", make_png(1, 1, solid_rgba(1, 1)))
    # normal screenshot-like 320x200 gradient
    save(out / "gradient_320x200.png", make_png(320, 200, gradient_rgba(320, 200)))
    # with metadata chunks
    meta = [
        chunk(b"tEXt", b"Title\x00A test image"),
        chunk(b"tEXt", b"Software\x00ffe corpus generator"),
        chunk(b"gAMA", struct.pack(">I", 45455)),
        chunk(b"pHYs", struct.pack(">IIB", 2835, 2835, 1)),
        chunk(b"sRGB", b"\x00"),
        chunk(b"tIME", struct.pack(">HBBBBB", 2026, 9, 13, 12, 0, 0)),
        chunk(b"zzZz", b"unknown ancillary chunk payload"),  # unknown, must not break
    ]
    save(out / "metadata.png", make_png(64, 64, gradient_rgba(64, 64), meta))
    # larger
    save(out / "gradient_1024x768.png", make_png(1024, 768, gradient_rgba(1024, 768)))

    # --- corrupted variants ---
    good = make_png(32, 32, gradient_rgba(32, 32))
    # invalid signature
    save(out / "corrupt/bad_signature.png", b"\x00" * 8 + good[8:])
    # truncated (cut inside IDAT)
    save(out / "corrupt/truncated.png", good[: len(good) // 2])
    # bad CRC in IHDR: flip last CRC byte
    bad = bytearray(good)
    bad[29] ^= 0xFF  # IHDR CRC is at 8+4+13 = offset 25..29
    save(out / "corrupt/bad_crc.png", bytes(bad))
    # insane length: chunk length says 500 MB but file is small
    body = bytearray(SIG + ihdr(8, 8))
    body += struct.pack(">I", 500_000_000) + b"IDAT" + b"\x00" * 32
    save(out / "corrupt/insane_length.png", bytes(body))
    # missing IEND
    save(out / "corrupt/missing_iend.png", good[: good.rfind(b"IEND") - 4])
    # not a png but claims .png extension: fake text
    save(out / "corrupt/actually_text.png", b"this is definitely not a PNG file" * 10)

    build_wav(out / "wav")
    build_jpeg(out / "jpeg")


def build_wav(out: Path) -> None:
    import math
    import struct as st
    import wave

    out.mkdir(parents=True, exist_ok=True)
    # 1s 440Hz sine, 16-bit mono 44.1kHz (stdlib writer → guaranteed valid)
    path = out / "sine_440_16bit_mono.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = b"".join(
            st.pack("<h", int(20000 * math.sin(2 * math.pi * 440 * i / 44100)))
            for i in range(44100)
        )
        w.writeframes(frames)

    # stereo 8-bit with LIST INFO chunk injected manually
    path2 = out / "stereo_8bit_list.wav"
    with wave.open(str(path2), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(1)
        w.setframerate(22050)
        n = 22050
        frames = bytes((128 + int(60 * math.sin(2 * math.pi * 330 * i / 22050))) % 256
                       for i in range(n * 2))
        w.writeframes(frames)
    # splice a LIST INFO chunk between fmt and data
    raw = path2.read_bytes()
    info_payload = b"INFOISFT" + st.pack("<I", 4) + b"ffe\x00"
    list_chunk = b"LIST" + st.pack("<I", len(info_payload)) + info_payload
    raw = raw.replace(b"data", list_chunk + b"data", 1)
    path2.write_bytes(raw)

    # corrupt: RIFF size lies, and a chunk length that overruns
    bad = bytearray(path.read_bytes())
    bad[4:8] = st.pack("<I", 10 ** 9)
    save(out / "corrupt/wav_bad_riffsize.wav", bytes(bad))
    truncated = path.read_bytes()
    save(out / "corrupt/wav_truncated.wav", truncated[: len(truncated) // 2])


def build_jpeg(out: Path) -> None:
    from PIL import Image

    out.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (256, 128))
    img.putdata([(x * 255 // 255, y * 255 // 127, 100) for y in range(128) for x in range(256)])
    img.save(out / "gradient_256x128.jpg", quality=88)
    # with EXIF
    exif = Image.Exif()
    exif[0x010F] = "ffe-corpus"      # Make
    exif[0x0132] = "2026:09:13"      # DateTime
    img.save(out / "with_exif.jpg", quality=85, exif=exif)
    # grayscale
    img.convert("L").save(out / "gray_256x128.jpg", quality=80)

    # corrupt: chop bytes before EOI
    good = (out / "gradient_256x128.jpg").read_bytes()
    save(out / "corrupt/jpeg_truncated.jpg", good[: int(len(good) * 0.8)])
    # corrupt a marker header in place → parser must report lost sync
    mangled = bytearray(good)
    sof = good.find(b"\xff\xc0")
    if sof < 0:
        sof = good.find(b"\xff\xc2")
    mangled[sof:sof + 2] = b"\x12\x34"
    save(out / "corrupt/jpeg_desync.jpg", bytes(mangled))


if __name__ == "__main__":
    build_all(Path(__file__).resolve().parents[1] / "samples")
    print("corpus written to samples/")
