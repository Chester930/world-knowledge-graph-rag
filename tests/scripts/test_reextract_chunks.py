import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.kg.reextract_chunks import _content_loss_ratio, parse_chunk_specs, read_status


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


class ContentLossRatioTests(unittest.TestCase):
    """報告65 §6/§7 真實案例（57-CANARY5，N0050031 c101）：重抽後從3筆帶
    部分條件的Fact坍縮成1筆完全無條件的裸陳述，狀態仍是`completed`，需要
    獨立的機械式字數比對才能抓到，不能只看`task_queue.db`的狀態。"""

    def test_detects_severe_content_loss(self):
        before = [
            "雇主 依法應為所屬勞工辦理參加勞工保險而未辦理",
            "勞工 發生職業災害事故致死亡或失能",
            "雇主 處以補助金額相同額度之罰鍰 勞工發生職業災害事故致死亡或失能經依本法施行前"
            "職業災害勞工保護法第六條規定發給補助者",
        ]
        after = ["雇主 處以 補助金額相同額度之罰鍰"]
        ratio = _content_loss_ratio(before, after)
        self.assertLess(ratio, 0.7)

    def test_clean_fix_does_not_trigger(self):
        # 57-AGGR7 教科書案例：條件複述進每筆結果三元組，總字數不減反增
        before = [
            "雇主 依本法第二十四條第二項規定辦理 訓練",
            "訓練 申請補助 費用",
            "最低開班人數 應達 五人",
            "訓練時數 不得低於 八十小時",
        ]
        after = [
            "雇主 依本法第二十四條第二項規定辦理 訓練",
            "最低開班人數 （雇主依本法第二十四條第二項規定辦理訓練並申請訓練費用補助時）應達 五人",
            "訓練時數 （雇主依本法第二十四條第二項規定辦理訓練並申請訓練費用補助時）不得低於 八十小時",
        ]
        ratio = _content_loss_ratio(before, after)
        self.assertGreaterEqual(ratio, 1.0)

    def test_empty_before_is_not_applicable(self):
        self.assertIsNone(_content_loss_ratio([], ["新產生的事實"]))


if __name__ == "__main__":
    unittest.main()
