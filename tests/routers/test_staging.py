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
