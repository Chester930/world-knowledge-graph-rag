import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.kg.reextract_chunks import parse_chunk_specs, read_status


class ReextractChunksTests(unittest.TestCase):
    def test_parse_chunk_specs_expands_indices_and_multiple_specs(self):
        got = parse_chunk_specs(["docA:1,2", "docB:7"])
        self.assertEqual(got, [("docA", 1), ("docA", 2), ("docB", 7)])

    def test_parse_chunk_specs_keeps_colons_inside_source_name(self):
        self.assertEqual(parse_chunk_specs(["a:b:3"]), [("a:b", 3)])

    def test_parse_chunk_specs_rejects_bad_format(self):
        with self.assertRaises(ValueError):
            parse_chunk_specs(["docA"])
        with self.assertRaises(ValueError):
            parse_chunk_specs(["docA:"])

    def test_read_status_returns_queue_value_or_none(self):
        path = Path(tempfile.mkdtemp()) / "q.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE task_queue (kg_id TEXT, source TEXT, chunk_index INTEGER, "
            "status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO task_queue VALUES ('k','docA',1,'failed','2026-09-20 00:00:00')")
        conn.commit()
        conn.close()
        self.assertEqual(read_status(path, "k", "docA", 1), "failed")
        self.assertIsNone(read_status(path, "k", "docA", 2))


if __name__ == "__main__":
    unittest.main()
