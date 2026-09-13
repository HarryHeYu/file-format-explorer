import unittest
from pathlib import Path

from ffe.api import inspect as ffe_inspect
from ffe.core.search import parse_hex_query, search_file

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class TestHexParsing(unittest.TestCase):
    def test_accepts_various_forms(self):
        self.assertEqual(parse_hex_query("50 4B 03 04"), bytes.fromhex("504b0304"))
        self.assertEqual(parse_hex_query("504b0304"), bytes.fromhex("504b0304"))
        self.assertEqual(parse_hex_query("0x504B"), bytes.fromhex("504b"))
        self.assertEqual(parse_hex_query("5 0"), b"P")  # spaces stripped first
        self.assertIsNone(parse_hex_query("xyz"))
        self.assertIsNone(parse_hex_query("5 0 1"))


class TestSearchFile(unittest.TestCase):
    def test_finds_ascii_matches(self):
        p = SAMPLES / "corrupt/actually_text.png"
        # file is "this is definitely not a PNG file" repeated 10 times
        hits = search_file(str(p), b"not a PNG")
        self.assertEqual(len(hits), 10)
        self.assertEqual(hits[0], 19)

    def test_match_spanning_window_boundary(self):
        p = SAMPLES / "corrupt/actually_text.png"
        # window of 8 forces matches to straddle boundaries
        self.assertEqual(len(search_file(str(p), b"not a PNG", window=8)), 10)

    def test_limit(self):
        p = SAMPLES / "corrupt/actually_text.png"
        self.assertEqual(len(search_file(str(p), b"s", limit=5)), 5)


class TestWav(unittest.TestCase):
    def test_mono_sine(self):
        r = ffe_inspect(SAMPLES / "wav/sine_440_16bit_mono.wav")
        self.assertEqual(r.format_name, "WAV")
        self.assertEqual(r.messages, [])
        audio = r.root.metadata["audio"]
        self.assertEqual(audio["sampleRate"], 44100)
        self.assertEqual(audio["channels"], 1)
        self.assertEqual(audio["bitsPerSample"], 16)
        self.assertIn("PCM", audio["codec"])
        self.assertAlmostEqual(audio["durationSec"], 1.0, places=2)
        # fmt fields are individually addressable
        names = [n.name for n in r.root.walk()]
        for field in ("Audio format", "Channels", "Sample rate", "Byte rate",
                      "Block align", "Bits per sample"):
            self.assertIn(field, names)

    def test_stereo_with_list(self):
        r = ffe_inspect(SAMPLES / "wav/stereo_8bit_list.wav")
        ids = [c.name for c in r.root.children]
        self.assertIn("LIST", ids)  # spliced INFO chunk must survive traversal
        audio = r.root.metadata["audio"]
        self.assertEqual(audio["channels"], 2)
        self.assertEqual(audio["sampleRate"], 22050)

    def test_bad_riff_size_reported(self):
        r = ffe_inspect(SAMPLES / "wav/corrupt/wav_bad_riffsize.wav")
        self.assertTrue(any("truncated" in m for m in r.messages))

    def test_truncated_no_crash(self):
        r = ffe_inspect(SAMPLES / "wav/corrupt/wav_truncated.wav")
        self.assertTrue(len(r.messages) > 0)


class TestJpeg(unittest.TestCase):
    def test_gradient(self):
        r = ffe_inspect(SAMPLES / "jpeg/gradient_256x128.jpg")
        self.assertEqual(r.format_name, "JPEG")
        img = r.root.metadata["image"]
        self.assertEqual(img["width"], 256)
        self.assertEqual(img["height"], 128)
        self.assertEqual(img["components"], 3)
        self.assertEqual(r.messages, [])
        names = [n.name for n in r.root.walk()]
        for m in ("SOF0 (Baseline DCT)", "DQT", "DHT (Huffman table)", "SOS", "EOI"):
            self.assertTrue(any(n.startswith(m.split(" ")[0]) for n in names), m)

    def test_exif_detected(self):
        r = ffe_inspect(SAMPLES / "jpeg/with_exif.jpg")
        names = [n.name for n in r.root.walk()]
        self.assertTrue(any(n.startswith("APP1") for n in names))

    def test_grayscale(self):
        r = ffe_inspect(SAMPLES / "jpeg/gray_256x128.jpg")
        self.assertEqual(r.root.metadata["image"]["components"], 1)

    def test_truncated_flags_missing_eoi(self):
        r = ffe_inspect(SAMPLES / "jpeg/corrupt/jpeg_truncated.jpg")
        self.assertTrue(any("EOI" in m for m in r.messages))

    def test_desync_no_crash(self):
        r = ffe_inspect(SAMPLES / "jpeg/corrupt/jpeg_desync.jpg")
        self.assertTrue(len(r.messages) > 0)


class TestFormatDetection(unittest.TestCase):
    def test_all_real_formats(self):
        cases = {
            "wav/sine_440_16bit_mono.wav": "WAV",
            "jpeg/gradient_256x128.jpg": "JPEG",
            "minimal.png": "PNG",
        }
        for rel, fmt in cases.items():
            r = ffe_inspect(SAMPLES / rel)
            self.assertEqual(r.format_name, fmt, rel)

    def test_wrong_extensions(self):
        # save a WAV as .png and a JPEG as .wav — magic must win
        wav = (SAMPLES / "wav/sine_440_16bit_mono.wav").read_bytes()
        jpg = (SAMPLES / "jpeg/gradient_256x128.jpg").read_bytes()
        f1 = SAMPLES / "fake_image.png"
        f2 = SAMPLES / "fake_audio.wav"
        f1.write_bytes(wav)
        f2.write_bytes(jpg)
        try:
            self.assertEqual(ffe_inspect(f1).format_name, "WAV")
            self.assertEqual(ffe_inspect(f2).format_name, "JPEG")
        finally:
            f1.unlink()
            f2.unlink()


if __name__ == "__main__":
    unittest.main()
