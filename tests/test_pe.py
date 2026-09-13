import unittest
from pathlib import Path

from ffe.api import inspect as ffe_inspect

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class TestPE(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # PE corpus is copied from the local system (copyrighted MS binaries,
        # not in git). On a fresh clone these tests are skipped gracefully.
        exe = SAMPLES / "pe/notepad.exe"
        if not exe.exists():
            src = Path(r"C:\Windows\System32\notepad.exe")
            if src.exists():
                exe.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy(src, exe)
            else:
                raise unittest.SkipTest(
                    "PE corpus missing and C:\\Windows\\System32\\notepad.exe not found")
        cls.notepad = ffe_inspect(SAMPLES / "pe/notepad.exe")
        dll = SAMPLES / "pe/winbrand.dll"
        if not dll.exists():
            src = Path(r"C:\Windows\System32\winbrand.dll")
            if src.exists():
                import shutil
                shutil.copy(src, dll)
        cls.dll = ffe_inspect(dll) if dll.exists() else None

    def test_exports(self):
        if self.dll is None:
            self.skipTest("winbrand.dll unavailable")
        r = self.dll
        exp = r.root.metadata["pe"].get("exports")
        self.assertIsNotNone(exp)
        self.assertEqual(exp["dllName"].upper(), "WINBRAND.DLL")
        et = next(c for c in r.root.children if c.name == "Export Table")
        fnodes = next(c for c in et.children if c.name == "Exported Functions")
        self.assertGreater(len(fnodes.children), 0)

    def test_notepad_basics(self):
        r = self.notepad
        self.assertEqual(r.format_name, "PE")
        self.assertEqual(r.messages, [])
        pe = r.root.metadata["pe"]
        self.assertEqual(pe["machine"], "x64")
        self.assertEqual(pe["subsystem"], "Windows GUI")
        self.assertFalse(pe["isDll"])
        self.assertGreater(pe["imageBase"], 0)

    def test_notepad_sections(self):
        r = self.notepad
        names = {s["name"] for s in r.root.metadata["pe"]["sections"]}
        self.assertTrue({"text", "rdata", "data", "rsrc"} <= {n.lstrip(".") for n in names})

    def test_section_raw_data_nodes(self):
        r = self.notepad
        text = next(n for n in r.root.walk() if n.name == ".text")
        raw = next(x for x in text.children if x.name == "Raw data")
        self.assertGreater(raw.size, 0)

    def test_imports_realistic(self):
        r = self.notepad
        imp = r.root.metadata["pe"]["imports"]
        self.assertGreater(imp["dlls"], 3)
        self.assertGreater(imp["functions"], 10)
        it = next(c for c in r.root.children if c.name == "Import Table")
        # modern notepad imports via api-ms-win-* umbrella DLLs
        self.assertTrue(any(c.name.upper().startswith("API-MS-WIN-") for c in it.children))

    def test_import_function_names(self):
        r = self.notepad
        it = next(c for c in r.root.children if c.name == "Import Table")
        gdi = next(c for c in it.children if c.name.upper() == "GDI32.DLL")
        funcs = next(c for c in gdi.children if c.name == "Functions")
        fnames = [c.name for c in funcs.children]
        self.assertTrue(fnames)
        self.assertTrue(all(isinstance(f, str) and f for f in fnames))

    def test_entry_point_maps_into_text(self):
        r = self.notepad
        pe = r.root.metadata["pe"]
        ep = pe["entryPoint"]
        text = next(s for s in pe["sections"] if s["name"] == ".text")
        self.assertTrue(text["vaddr"] <= ep < text["vaddr"] + text["rawSize"] + 0x1000)

    def test_depth_vs_walk_consistency(self):
        # every COFF field must be individually addressable
        names = [n.name for n in self.notepad.root.walk()]
        for field in ("e_magic", "e_lfanew", "Machine", "NumberOfSections",
                      "AddressOfEntryPoint", "ImageBase", "Subsystem",
                      "VirtualAddress", "SizeOfRawData", "Characteristics"):
            self.assertIn(field, names)

    def test_bad_pe_signature(self):
        r = ffe_inspect(SAMPLES / "pe/corrupt/bad_pe_sig.dll")
        self.assertFalse(r.ok)
        self.assertTrue(any("PE signature" in m for m in r.messages))

    def test_truncated_flags_sections(self):
        r = ffe_inspect(SAMPLES / "pe/corrupt/truncated.exe")
        errs = [n for n in r.root.walk() if n.validation == "error"]
        self.assertTrue(any("exceeds" in (e.description or "") for e in errs))

    def test_mz_text_file_not_pe(self):
        p = SAMPLES / "pe/corrupt/mz_text.bin"
        p.write_bytes(b"MZ this is text, e_lfanew points nowhere")
        try:
            r = ffe_inspect(p)
            if r is not None:  # may be recognized as PE but must fail validation
                self.assertFalse(r.ok)
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
