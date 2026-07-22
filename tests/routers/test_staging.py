from uuid import uuid4

import pytest

from core import config
from routers.staging import _trigger_extraction
from services import document_record_service, ingestion_service, task_queue_service


@pytest.mark.asyncio
async def test_trigger_extraction_enqueues_produced_chunks(tmp_path, monkeypatch):
    """對應 § 3.1.2「立即觸發抽取任務」：文件搬進 KG 資料夾後，
    CHUNKREADY 產出的 SVO chunk 應被登記進 task_queue.db。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage("單句無代名詞。", "note.md", kg_folder)

    kg_id = uuid4()
    await _trigger_extraction(doc_folder, kg_id)

    pending = task_queue_service.next_pending(config.task_queue_db_path(), str(kg_id))
    assert pending == (str(kg_id), "note.md", 1)


@pytest.mark.asyncio
async def test_trigger_extraction_records_svo_chunk_total(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage("第一句話。" * 100, "big.txt", kg_folder)

    await _trigger_extraction(doc_folder, uuid4())

    updated = document_record_service.read_record(doc_folder)
    assert updated.svo_total_chunks > 0


@pytest.mark.asyncio
async def test_trigger_extraction_is_noop_when_record_missing(tmp_path, monkeypatch):
    """資料夾沒有記錄檔（異常狀態）時不應拋出例外，只是靜默跳過。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    empty_folder = tmp_path / "no-record"
    empty_folder.mkdir()

    await _trigger_extraction(empty_folder, uuid4())  # 不應拋出例外


@pytest.mark.asyncio
async def test_trigger_extraction_skips_embedding_when_provider_not_initialized(tmp_path, monkeypatch):
    """對應誠實侷限：測試環境未呼叫 `init_providers()`，`get_embedding_provider()`
    會拋出 RuntimeError，應優雅跳過向量化，不影響切塊與排隊本身。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage("單句無代名詞。", "note.md", kg_folder)

    await _trigger_extraction(doc_folder, uuid4())  # 不應拋出例外

    pending = task_queue_service.next_pending(config.task_queue_db_path())
    assert pending is not None


@pytest.mark.asyncio
async def test_trigger_extraction_embeds_chunks_when_provider_available(tmp_path, monkeypatch):
    """對應 2026-07-22 使用者確認：切塊當下順便向量化，供未來來源篩選使用。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "馬斯克創立了太空公司。他隨後研發了獵鷹火箭。", "note.md", kg_folder,
    )

    class FakeEmbedding:
        dim = 4
        model_name = "fake-embedding"

        def encode(self, text: str) -> list[float]:
            return [0.0] * self.dim

        def encode_batch(self, texts: list[str]) -> list[list[float]]:
            return [self.encode(t) for t in texts]

    class FakeResult:
        records: list = []

    class FakeDriver:
        def __init__(self):
            self.calls = []

        async def execute_query(self, query, **params):
            self.calls.append((query, params))
            return FakeResult()

    fake_driver = FakeDriver()
    monkeypatch.setattr("routers.staging.get_embedding_provider", lambda: FakeEmbedding())
    monkeypatch.setattr("routers.staging.get_driver", lambda: fake_driver)

    await _trigger_extraction(doc_folder, uuid4())

    embed_calls = [c for c in fake_driver.calls if "c.embedding" in c[0]]
    assert len(embed_calls) >= 1
