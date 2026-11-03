import tempfile
import unittest
from pathlib import Path

from scripts.d1_restore_drill import prepare_export


class D1RestoreDrillTests(unittest.TestCase):
    def test_oversized_collection_chunk_is_rewritten_as_bounded_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sql"
            target = root / "prepared.sql"
            value = "[" + "'" * 3 + "x" * 120 + "]"
            source.write_text(
                "INSERT INTO \"portal_collection_chunks\" (\"name\",\"version_id\",\"chunk_no\",\"value_json\") "
                "VALUES('ledger','v1',0,'" + value.replace("'", "''") + "');\n",
                encoding="utf-8",
            )
            self.assertEqual(prepare_export(source, target, max_statement_chars=220, append_chars=25), 1)
            prepared = target.read_text(encoding="utf-8")
            self.assertIn("VALUES('ledger','v1',0,'');", prepared)
            self.assertGreater(prepared.count("UPDATE \"portal_collection_chunks\""), 1)
            self.assertLessEqual(max(map(len, prepared.splitlines())), 220)

    def test_normal_sized_exports_are_copied_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.sql"
            target = root / "prepared.sql"
            source.write_text("SELECT 1;\n", encoding="utf-8")
            self.assertEqual(prepare_export(source, target), 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "SELECT 1;\n")


if __name__ == "__main__":
    unittest.main()
