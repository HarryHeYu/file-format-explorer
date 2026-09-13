import unittest
from pathlib import Path

from ffe.api import inspect as ffe_inspect

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class TestZip(unittest.TestCase):
    def test_mixed_archive(self):
        r = ffe_inspect(SAMPLES / "zip/mixed.zip")
        self.assertEqual(r.format_name, "ZIP")
        self.assertEqual(r.messages, [])
        meta = r.root.metadata["zip"]
        self.assertEqual(meta["entries"], 4)
        self.assertEqual(meta["files"], 4)
        self.assertEqual(sorted(meta["methods"]), ["Deflate", "Stored"])
        names = [c.name for c in r.root.children]
        self.assertEqual(names, ["EOCD", "Central Directory", "Local Entries"])

    def test_central_local_relation(self):
        r = ffe_inspect(SAMPLES / "zip/mixed.zip")
        r.root.link_parents()
        cd = next(c for c in r.root.children if c.name == "Central Directory")
        entry = next(c for c in cd.children if c.name == "readme.txt")
        rel = entry.metadata["relation"]
        local = r.root.find_id(rel["nodeId"])
        self.assertIsNotNone(local)
        self.assertEqual(rel["label"], "Local File Header")
        self.assertIn("Local Entries", local.path_string())
        self.assertIn("Local File Header at 0x", entry.description)

    def test_crc_valid_for_all_entries(self):
        r = ffe_inspect(SAMPLES / "zip/mixed.zip")
        locals_node = next(c for c in r.root.children if c.name == "Local Entries")
        for entry in locals_node.children:
            data = next((x for x in entry.children if x.name == "File data"), None)
            if data is not None:
                self.assertNotEqual(data.validation, "error", entry.name)

    def test_bad_crc_detected(self):
        r = ffe_inspect(SAMPLES / "zip/corrupt/bad_data_crc.zip")
        self.assertTrue(any("CRC mismatch" in m and "readme.txt" in m for m in r.messages))
        errs = [n for n in r.root.walk() if n.validation == "error"]
        self.assertTrue(any("readme.txt" in (n.path_string()) for n in errs))

    def test_truncated_zip_salvaged(self):
        r = ffe_inspect(SAMPLES / "zip/corrupt/truncated.zip")
        self.assertEqual(r.format_name, "ZIP")
        self.assertTrue(any("EOCD" in m for m in r.messages))
        names = [n.name for n in r.root.walk()]
        self.assertIn("stored.bmp", names)  # entries before the cut are salvaged

    def test_not_a_zip(self):
        self.assertIsNone(ffe_inspect(SAMPLES / "zip/corrupt/not_a_zip.zip"))

    def test_empty_entry_no_crash(self):
        r = ffe_inspect(SAMPLES / "zip/mixed.zip")
        locals_node = next(c for c in r.root.children if c.name == "Local Entries")
        empty = next(c for c in locals_node.children if c.name == "empty.txt")
        self.assertEqual(empty.validation, "")


class TestReport(unittest.TestCase):
    def test_markdown_report(self):
        from ffe.cli import main
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["report", str(SAMPLES / "zip/mixed.zip")])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("# ZIP Analysis: mixed.zip", out)
        self.assertIn("## Structure", out)
        self.assertIn("VALID", out)

    def test_json_report(self):
        import json as jsonlib
        from ffe.cli import main
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["report", str(SAMPLES / "zip/corrupt/bad_data_crc.zip"), "--json"])
        self.assertEqual(code, 0)
        doc = jsonlib.loads(buf.getvalue())
        self.assertEqual(doc["format"], "ZIP")

    def test_corrupt_report_lists_errors(self):
        from ffe.cli import main
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["report", str(SAMPLES / "zip/corrupt/bad_data_crc.zip")])
        self.assertIn("CRC MISMATCH", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
