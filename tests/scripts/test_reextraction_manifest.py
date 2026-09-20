import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.kg.reextraction_manifest import build_manifest

KG = "kg-1"


def _make_db(rows):
    path = str(Path(tempfile.mkdtemp()) / "q.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE task_queue (kg_id TEXT, source TEXT, chunk_index INTEGER, status TEXT, updated_at TEXT)"
    )
    conn.executemany("INSERT INTO task_queue VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


class ReextractionManifestTests(unittest.TestCase):
    def test_lists_only_chunks_since_cutoff_and_groups_by_source_and_day(self):
        db = _make_db([
            (KG, "docA", 1, "completed", "2026-09-08 01:00:00"),
            (KG, "docA", 2, "completed", "2026-09-15 01:00:00"),
            (KG, "docA", 3, "completed", "2026-09-15 01:05:00"),
        ])
        text = build_manifest(db, KG, "2026-09-12")
        self.assertIn("| 2026-09-15 | 01:00–01:05 | docA | 2 | 2, 3 | completed |", text)
        self.assertNotIn("| 1 |", text.split("非 completed")[0].split("|---|---|---|---|---|---|")[1])

    def test_reports_failed_and_pending_even_if_older_than_cutoff(self):
        db = _make_db([
            (KG, "docA", 5, "failed", "2026-09-08 01:00:00"),
            (KG, "docB", 9, "pending", "2026-09-16 01:00:00"),
            (KG, "docB", 10, "completed", "2026-09-16 01:00:00"),
        ])
        text = build_manifest(db, KG, "2026-09-12")
        unfinished = text.split("非 completed")[1]
        self.assertIn("| docA | 5 | failed |", unfinished)
        self.assertIn("| docB | 9 | pending |", unfinished)
        self.assertNotIn("| docB | 10 |", unfinished)

    def test_no_unfinished_chunks(self):
        db = _make_db([(KG, "docA", 1, "completed", "2026-09-15 01:00:00")])
        self.assertIn("| （無） |", build_manifest(db, KG, "2026-09-12"))


if __name__ == "__main__":
    unittest.main()
