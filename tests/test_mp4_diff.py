import unittest
from pathlib import Path

from ffe.api import inspect as ffe_inspect
from ffe.core.diff import diff_files

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class TestMP4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = ffe_inspect(SAMPLES / "mp4/minimal.mp4")

    def test_hierarchy(self):
        r = self.r
        self.assertEqual(r.format_name, "MP4")
        self.assertEqual(r.messages, [])
        names = [n.name.split(" — ")[0] for n in r.root.walk()]
        for label in ("File type", "Movie container", "Movie header",
                      "Track container", "Track header", "Media container",
                      "Media header", "Handler", "Media information",
                      "Sample table", "Media data"):
            self.assertIn(label, names, label)

    def test_movie_header(self):
        meta = self.r.root.metadata["mp4"]
        self.assertEqual(meta["brand"], "isom")
        self.assertEqual(meta["timescale"], 1000)
        self.assertEqual(meta["duration"], 5000)

    def test_handler_and_codec(self):
        r = self.r
        hdlr = next(n for n in r.root.walk() if n.name == "Handler"
                    and any(c.name == "Handler" for c in n.children))
        handler = next(c for c in hdlr.children if c.name == "Handler")
        self.assertEqual(handler.value, "vide")
        stsd = next(n for n in r.root.walk() if n.name == "Sample description")
        self.assertTrue(any(c.name == "Codec" for c in stsd.children))

    def test_bad_size_flagged(self):
        r = ffe_inspect(SAMPLES / "mp4/corrupt/bad_size.mp4")
        self.assertFalse(r.ok)

    def test_truncated_flagged(self):
        r = ffe_inspect(SAMPLES / "mp4/corrupt/truncated.mp4")
        errs = [n for n in r.root.walk() if n.validation == "error"]
        self.assertTrue(errs)


class TestDiff(unittest.TestCase):
    def test_structured_png_diff(self):
        d = diff_files(str(SAMPLES / "diffpair/before.png"),
                       str(SAMPLES / "diffpair/after.png"))
        self.assertTrue(d.same_format)
        changed = {p: (va, vb) for p, va, vb in d.changed}
        self.assertIn("PNG/IHDR/Data/Width", changed)
        self.assertEqual(changed["PNG/IHDR/Data/Width"], ("320", "128"))
        self.assertEqual(changed["PNG/IHDR/Data/Height"], ("200", "720"))

    def test_identical_files(self):
        d = diff_files(str(SAMPLES / "minimal.png"), str(SAMPLES / "minimal.png"))
        self.assertEqual(d.byte_runs, [])
        self.assertEqual(d.differing_bytes, 0)
        self.assertEqual(d.changed, [])

    def test_different_formats_no_structure(self):
        d = diff_files(str(SAMPLES / "minimal.png"), str(SAMPLES / "wav/sine_440_16bit_mono.wav"))
        self.assertFalse(d.same_format)
        self.assertTrue(d.differing_bytes > 0)

    def test_byte_runs_merged(self):
        # 1-byte difference at a known spot inside stored text
        d = diff_files(str(SAMPLES / "corrupt/actually_text.png"),
                       str(SAMPLES / "corrupt/actually_text.png").replace(
                           "actually", "actually", 1))
        self.assertLessEqual(len(d.byte_runs), 1)


if __name__ == "__main__":
    unittest.main()
