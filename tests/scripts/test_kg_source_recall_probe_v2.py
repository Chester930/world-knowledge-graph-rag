import importlib
import os
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 被測模組在匯入時會呼叫 `load_env()`，把 kg-reextract 的 `.env` 寫進 `os.environ`
# （收集階段即發生、整個 pytest 行程共用），會汙染 `Settings(_env_file=None)` 這類
# 依賴「沒有環境變數覆寫」的測試（例如 tests/core/test_embedding_migration.py）。
# 匯入後立刻還原環境變數，讓本檔不留下行程級副作用。
_ENV_BEFORE_IMPORT = dict(os.environ)
try:
    from scripts.eval.kg_source_recall_probe_v2 import triple_candidates  # noqa: E402
finally:
    os.environ.clear()
    os.environ.update(_ENV_BEFORE_IMPORT)


class TripleCandidatesTest(unittest.TestCase):
    CITES = [
        {"source_doc_id": "d1", "source_svo_chunk_index": 2, "article_no": "第 2 條"},
        {"source_doc_id": "d2", "source_svo_chunk_index": 5, "article_no": None},
        {"source_doc_id": "d2", "source_svo_chunk_index": 5, "article_no": None},
    ]

    def test_last_takes_only_latest_citation(self):
        out = triple_candidates({"citations": self.CITES}, "last")
        self.assertEqual([(c["source_doc_id"], c["source_svo_chunk_index"]) for c in out], [("d2", 5)])

    def test_all_dedups_citations(self):
        out = triple_candidates({"citations": self.CITES}, "all")
        self.assertEqual([(c["source_doc_id"], c["source_svo_chunk_index"]) for c in out], [("d1", 2), ("d2", 5)])
        self.assertEqual(out[0]["article_no"], "第 2 條")

    def test_no_citations_gives_no_candidates(self):
        self.assertEqual(triple_candidates({"citations": []}, "last"), [])


class ImportHasNoEnvironSideEffectTest(unittest.TestCase):
    """匯入 `kg_source_recall_probe_v2` 不得修改 `os.environ`（報告185 C3）。

    以假的 `.env` 內容（只對 kg-reextract 的兩個路徑生效）驅動 `load_env()`，
    不依賴本機是否真有該檔，因此在任何機器上都能偵測「匯入期載入環境」的回歸。
    """

    MODULE = "scripts.eval.kg_source_recall_probe_v2"
    SENTINEL = "PROBE_V2_SENTINEL_ENV_KEY"

    def _fake_env_patches(self):
        real_exists, real_read_text = Path.exists, Path.read_text

        def is_fake(p):
            return str(p).replace("\\", "/").endswith(".claude/worktrees/kg-reextract/.env")

        def fake_exists(self_):
            return True if is_fake(self_) else real_exists(self_)

        def fake_read_text(self_, *a, **k):
            if is_fake(self_):
                return f"# fake\n{ImportHasNoEnvironSideEffectTest.SENTINEL}=1\n"
            return real_read_text(self_, *a, **k)

        return (
            unittest.mock.patch.object(Path, "exists", fake_exists),
            unittest.mock.patch.object(Path, "read_text", fake_read_text),
        )

    def test_import_does_not_touch_environ(self):
        saved = sys.modules.pop(self.MODULE, None)
        p_exists, p_read = self._fake_env_patches()
        try:
            with unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(self.SENTINEL, None)
                before = dict(os.environ)
                with p_exists, p_read:
                    importlib.import_module(self.MODULE)
                self.assertNotIn(self.SENTINEL, os.environ)
                self.assertEqual(before, dict(os.environ))
        finally:
            sys.modules.pop(self.MODULE, None)
            if saved is not None:
                sys.modules[self.MODULE] = saved

    def test_load_env_still_loads_when_called_explicitly(self):
        # 證明上一個測試的假 `.env` 機制確實有效（否則「不變」可能只是假陽性）
        mod = importlib.import_module(self.MODULE)
        p_exists, p_read = self._fake_env_patches()
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(self.SENTINEL, None)
            with p_exists, p_read:
                mod.load_env()
            self.assertEqual(os.environ.get(self.SENTINEL), "1")


if __name__ == "__main__":
    unittest.main()
