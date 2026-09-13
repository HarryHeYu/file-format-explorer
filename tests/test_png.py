import unittest
from pathlib import Path

from ffe.api import inspect as ffe_inspect
from ffe.core.datasource import DataSource
from ffe.core.registry import detect
from tests.corpus import build_all

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def setUpModule():
    build_all(SAMPLES)


class TestDetection(unittest.TestCase):
    def test_detects_real_png(self):
        with DataSource(SAMPLES / "gradient_320x200.png") as src:
            p = detect(src)
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "PNG")

    def test_wrong_extension_still_png_by_magic(self):
        # a real PNG saved with .txt must still be detected via magic
        data = (SAMPLES / "minimal.png").read_bytes()
        fake = SAMPLES / "abc.txt"
        fake.write_bytes(data)
        with DataSource(fake) as src:
            self.assertEqual(detect(src).name, "PNG")

    def test_text_file_not_detected(self):
        with DataSource(SAMPLES / "corrupt/actually_text.png") as src:
            self.assertIsNone(detect(src))


class TestValidPng(unittest.TestCase):
    def test_minimal(self):
        r = ffe_inspect(SAMPLES / "minimal.png")
        self.assertEqual(r.format_name, "PNG")
        names = [c.name for c in r.root.children]
        self.assertEqual(names, ["Signature", "IHDR", "IDAT", "IEND"])
        self.assertEqual(r.root.metadata["image"]["width"], 1)

    def test_ihdr_fields_selectable(self):
        r = ffe_inspect(SAMPLES / "gradient_320x200.png")
        ihdr = next(c for c in r.root.children if c.name == "IHDR")
        data = next(c for c in ihdr.children if c.name == "Data")
        fields = {c.name: c for c in data.children}
        self.assertEqual(fields["Width"].value, 320)
        self.assertEqual(fields["Height"].value, 1080 - 880)  # 200
        # width field maps to bytes 0x10..0x14
        self.assertEqual(fields["Width"].offset, 0x10)
        self.assertEqual(fields["Width"].size, 4)
        self.assertEqual(fields["Width"].endian, "big")

    def test_crc_valid(self):
        r = ffe_inspect(SAMPLES / "metadata.png")
        for c in r.root.children:
            if c.name in ("IHDR", "IDAT", "IEND", "tEXt", "gAMA"):
                crc = next(x for x in c.children if x.name == "CRC")
                self.assertEqual(crc.validation, "ok", c.name)
        self.assertFalse([m for m in r.messages if "missing" in m])

    def test_unknown_chunk_graceful(self):
        r = ffe_inspect(SAMPLES / "metadata.png")
        types = [c.name for c in r.root.children]
        self.assertIn("zzZz", types)
        self.assertEqual(r.ok, True)


class TestCorruptedPng(unittest.TestCase):
    def test_bad_signature(self):
        # bad magic means "not a PNG at all" -> unrecognized (None)
        self.assertIsNone(ffe_inspect(SAMPLES / "corrupt/bad_signature.png"))

    def test_truncated_no_crash(self):
        r = ffe_inspect(SAMPLES / "corrupt/truncated.png")
        self.assertTrue(len(r.messages) > 0)

    def test_bad_crc_detected(self):
        r = ffe_inspect(SAMPLES / "corrupt/bad_crc.png")
        ihdr = next(c for c in r.root.children if c.name == "IHDR")
        crc = next(x for x in ihdr.children if x.name == "CRC")
        self.assertEqual(crc.validation, "error")
        self.assertIn("mismatch", crc.value)

    def test_insane_length_flagged(self):
        r = ffe_inspect(SAMPLES / "corrupt/insane_length.png")
        self.assertTrue(any("boundary" in m or "exceeds" in m or "truncated" in m for m in r.messages))

    def test_missing_iend(self):
        r = ffe_inspect(SAMPLES / "corrupt/missing_iend.png")
        self.assertTrue(any("IEND" in m for m in r.messages))

    def test_random_bytes_never_crash(self):
        import random
        random.seed(42)
        for i in range(50):
            data = bytes(random.randrange(256) for _ in range(random.randrange(0, 4000)))
            path = SAMPLES / "corrupt/fuzz_tmp.bin"
            path.write_bytes(data)
            try:
                ffe_inspect(path)  # None (unrecognized) or a ParseResult; must not raise
            finally:
                path.unlink()


class TestByteOwnership(unittest.TestCase):
    def test_deepest_node_for_width_byte(self):
        r = ffe_inspect(SAMPLES / "gradient_320x200.png")
        root = r.root
        root.link_parents()
        # byte 0x10 belongs to PNG > IHDR > Data > Width, and width is smallest
        off = 0x10
        best = None
        for n in root.walk():
            if n.offset <= off < n.end and n.size > 0:
                if best is None or n.size <= best.size:
                    best = n
        self.assertEqual(best.name, "Width")
        self.assertEqual(best.path_string(), "PNG / IHDR / Data / Width")


if __name__ == "__main__":
    unittest.main()
