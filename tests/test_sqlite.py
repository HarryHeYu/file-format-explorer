import unittest
from pathlib import Path

from ffe.api import inspect as ffe_inspect

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class TestSQLite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = ffe_inspect(SAMPLES / "sqlite/demo.sqlite")

    def test_header(self):
        r = self.r
        self.assertEqual(r.format_name, "SQLite")
        self.assertTrue(r.ok)
        meta = r.root.metadata["sqlite"]
        self.assertEqual(meta["pageSize"], 4096)
        self.assertEqual(meta["pageCount"], 4)

    def test_pages_classified(self):
        names = [n.name for n in self.r.root.walk()]
        self.assertTrue(any("Page 1" in n and "Leaf table" in n for n in names))
        self.assertTrue(any("Leaf index" in n for n in names))

    def test_schema_objects(self):
        r = self.r
        schema = next(c for c in r.root.children if c.name == "sqlite_schema")
        names = [c.name for c in schema.children]
        self.assertIn("table: users", names)
        self.assertIn("table: notes", names)
        self.assertIn("index: idx_users_name", names)

    def test_schema_relation_to_pages(self):
        r = self.r
        schema = next(c for c in r.root.children if c.name == "sqlite_schema")
        users = next(c for c in schema.children if c.name == "table: users")
        rel = users.metadata.get("relation")
        self.assertIsNotNone(rel)
        target = r.root.find_id(rel["nodeId"])
        self.assertIsNotNone(target)
        self.assertIn("Page", target.name)

    def test_rows_decoded(self):
        # users table rows carry id/name/score; find one known row
        names = [n.name for n in self.r.root.walk()]
        self.assertTrue(any("rowid 0" in n or "rowid 1" in n for n in names))
        row = next((n for n in self.r.root.walk()
                    if n.value and "user001" in str(n.value)), None)
        self.assertIsNotNone(row)

    def test_bad_magic(self):
        # corrupt magic = not a database at all → unrecognized
        self.assertIsNone(ffe_inspect(SAMPLES / "sqlite/corrupt/bad_magic.sqlite"))

    def test_truncated_no_crash(self):
        r = ffe_inspect(SAMPLES / "sqlite/corrupt/truncated.sqlite")
        self.assertIsNotNone(r)


if __name__ == "__main__":
    unittest.main()
