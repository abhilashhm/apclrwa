import json
import unittest

from cloudflare.d1 import D1Store


class CloudflareD1Tests(unittest.TestCase):
    def test_large_lists_are_split_and_can_be_reconstructed(self):
        original_limit = D1Store.CHUNK_BYTES
        try:
            setattr(D1Store, "CHUNK_BYTES", 40)
            value = [{"id": "1", "text": "abcdefghijk"}, {"id": "2", "text": "lmnopqrstuv"}]
            chunks = D1Store._chunks(value)
            self.assertGreater(len(chunks), 1)
            rebuilt = [item for chunk in chunks for item in json.loads(chunk)]
            self.assertEqual(rebuilt, value)
        finally:
            setattr(D1Store, "CHUNK_BYTES", original_limit)

    def test_save_statements_include_revision_guard(self):
        store = D1Store(object())
        old = {"events": [], "residents": []}
        new = {"events": [{"id": "E-1"}], "residents": []}
        statements, next_revision = store.save_statements(old, new, 4, "2026-10-20T00:00:00+00:00")
        sql = [statement for statement, _ in statements]
        self.assertEqual(next_revision, 5)
        self.assertEqual(sql[0], "DELETE FROM portal_revision_guard WHERE id = 1")
        self.assertIn("INSERT INTO portal_revision_guard", sql[1])
        self.assertIn("UPDATE portal_state SET revision", " ".join(sql))
        self.assertEqual(sql[-1], "DELETE FROM portal_revision_guard WHERE id = 1")


if __name__ == "__main__":
    unittest.main()
