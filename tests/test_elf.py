import unittest
from pathlib import Path

from ffe.api import inspect as ffe_inspect

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class TestELF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = ffe_inspect(SAMPLES / "elf/minimal64.elf")

    def test_header(self):
        r = self.r
        self.assertEqual(r.format_name, "ELF")
        self.assertEqual(r.messages, [])
        self.assertTrue(r.ok)
        meta = r.root.metadata["elf"]
        self.assertEqual(meta["class"], "ELF64")
        self.assertEqual(meta["machine"], "x86-64")
        self.assertEqual(meta["type"], "ET_EXEC")

    def test_fields_addressable(self):
        names = [n.name for n in self.r.root.walk()]
        for field in ("Magic", "Class", "Endianness", "Type", "Machine",
                      "Entry point", "Section header offset", "Number of sections",
                      "Flags", "Address", "Offset", "Size"):
            self.assertIn(field, names)

    def test_sections_named(self):
        names = [n.name for n in self.r.root.walk()]
        for sec in (".text", ".data", ".shstrtab", ".symtab", ".strtab"):
            self.assertIn(sec, names)

    def test_symbol_resolution(self):
        main = next(n for n in self.r.root.walk() if n.name == "main")
        self.assertIn("GLOBAL", main.value)
        self.assertEqual(main.value, "0xB0 (GLOBAL, 32 B)")

    def test_raw_data_nodes(self):
        text = next(n for n in self.r.root.walk() if n.name == ".text")
        raw = next(x for x in text.children if x.name == "Raw data")
        self.assertEqual(raw.offset, 0xB0)
        self.assertEqual(raw.size, 32)

    def test_bad_magic(self):
        self.assertIsNone(ffe_inspect(SAMPLES / "elf/corrupt/bad_magic.elf"))

    def test_truncated_flagged(self):
        r = ffe_inspect(SAMPLES / "elf/corrupt/truncated.elf")
        self.assertFalse(r.ok)
        self.assertTrue(any("truncated" in m.lower() for m in r.messages))

    def test_bad_shoff_flagged(self):
        r = ffe_inspect(SAMPLES / "elf/corrupt/bad_shoff.elf")
        self.assertFalse(r.ok)
        errs = [n for n in r.root.walk() if n.validation == "error"]
        self.assertTrue(errs)

    def test_elf32_path(self):
        # regression: the 32-bit header unpack used to crash on every ELF32 file
        r = ffe_inspect(SAMPLES / "elf/minimal32.elf")
        self.assertIsNotNone(r)
        self.assertTrue(r.ok)
        self.assertEqual(r.messages, [])
        meta = r.root.metadata["elf"]
        self.assertEqual(meta["class"], "ELF32")
        self.assertEqual(meta["machine"], "x86")
        names = [n.name for n in r.root.walk()]
        self.assertIn(".text", names)
        self.assertIn("PT_LOAD", names)

    def test_invalid_class_flagged(self):
        # EI_CLASS mutated to garbage must not crash (it used to fall into the
        # broken 32-bit path) — parser must produce an error tree instead
        data = bytearray((SAMPLES / "elf/minimal64.elf").read_bytes())
        data[4] = 0x07
        p = SAMPLES / "elf/corrupt/_tmp_bad_class.elf"
        p.write_bytes(bytes(data))
        try:
            r = ffe_inspect(p)
            self.assertFalse(r.ok)
            self.assertTrue(any("class" in m.lower() or "encoding" in m.lower()
                                for m in r.messages))
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
