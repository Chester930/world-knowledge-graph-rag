import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from core import config
from models.knowledge_graph import KnowledgeGraph
from services import document_record_service, extraction_worker, ingestion_service, task_queue_service
from services import svo_service


class FakeLLM:
    def __init__(self, payload: str | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error

    async def generate(self, prompt: str) -> str:
        return await self.generate_json(prompt)

    async def stream(self, prompt: str):
        yield await self.generate_json(prompt)

    async def generate_json(self, prompt: str) -> str:
        if self.error is not None:
            raise self.error
        return self.payload


class SpyDriver:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, **params):
        self.calls.append((query.strip(), params))
        return None


def _raise_runtime_error():
    raise RuntimeError("provider 尚未初始化")


def _make_kg(kg_id, folder_path: str) -> KnowledgeGraph:
    now = datetime.now(timezone.utc)
    return KnowledgeGraph(
        id=kg_id, name="KG-1", description="", folder_path=folder_path,
        is_public=True, created_at=now, updated_at=now,
    )


def _patch_kg_repo(monkeypatch, kg: KnowledgeGraph | None):
    class FakeRepo:
        def __init__(self, driver):
            self.driver = driver

        async def get(self, kg_id):
            return kg if (kg is not None and kg_id == kg.id) else None

    monkeypatch.setattr("services.extraction_worker.KGRepository", FakeRepo)


def _read_status(db_path, kg_id: str, source: str, chunk_index: int) -> str | None:
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT status FROM task_queue WHERE kg_id = ? AND source = ? AND chunk_index = ?",
            (kg_id, source, chunk_index),
        ).fetchone()
        return row[0] if row else None


async def _seed_pending_chunk(tmp_path, kg_id) -> tuple:
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage("馬斯克創立了太空公司。", "note.md", kg_folder)
    await svo_service.trigger_extraction(SpyDriver(), doc_folder, kg_id)

    pending = task_queue_service.next_pending(config.task_queue_db_path(), str(kg_id))
    assert pending is not None
    _, source, chunk_index = pending
    return kg_folder, doc_folder, source, chunk_index


@pytest.mark.asyncio
async def test_process_one_success_merges_triples_and_marks_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_id = uuid4()
    kg_folder, doc_folder, source, chunk_index = await _seed_pending_chunk(tmp_path, kg_id)

    _patch_kg_repo(monkeypatch, _make_kg(kg_id, str(kg_folder)))
    llm = FakeLLM(json.dumps([
        {"subject": "馬斯克", "verb": "創立", "object": "太空公司", "rel_type": "CAUSES"},
    ]))
    monkeypatch.setattr("services.extraction_worker.get_llm_provider", lambda: llm)
    monkeypatch.setattr("services.extraction_worker.get_embedding_provider", _raise_runtime_error)

    merged = []

    async def _fake_merge(driver, kg_id_arg, triples, **kwargs):
        merged.append((kg_id_arg, triples))

    monkeypatch.setattr("services.extraction_worker.merge_triples_to_graph", _fake_merge)

    await extraction_worker._process_one(SpyDriver(), str(kg_id), source, chunk_index)

    assert len(merged) == 1
    merged_kg_id, triples = merged[0]
    assert merged_kg_id == kg_id
    assert len(triples) == 1
    assert triples[0].source_svo_chunk_index == chunk_index
    assert triples[0].source_svo_chunk_file
    assert triples[0].source_sentence_start == 1
    # § 3.1.4 §c（2026-08-18）：source_doc_id 先前從未被賦值，現應決定性推導
    assert triples[0].source_doc_id == document_record_service.document_uuid(source)
    # 2026-08-19：冗餘存下原始文件名稱字串本身，見 SVOTriple.source docstring
    assert triples[0].source == source

    assert _read_status(config.task_queue_db_path(), str(kg_id), source, chunk_index) == "completed"

    updated_record = document_record_service.read_record(doc_folder)
    assert updated_record.extraction_status == "completed"
    assert updated_record.chunk_progress == chunk_index
    assert chunk_index in updated_record.completed_chunk_indices


@pytest.mark.asyncio
async def test_process_one_without_triples_skips_merge_but_still_completes(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_id = uuid4()
    kg_folder, doc_folder, source, chunk_index = await _seed_pending_chunk(tmp_path, kg_id)

    _patch_kg_repo(monkeypatch, _make_kg(kg_id, str(kg_folder)))
    monkeypatch.setattr("services.extraction_worker.get_llm_provider", lambda: FakeLLM(json.dumps([])))
    monkeypatch.setattr("services.extraction_worker.get_embedding_provider", _raise_runtime_error)

    merge_called = []
    monkeypatch.setattr(
        "services.extraction_worker.merge_triples_to_graph",
        lambda *a, **k: merge_called.append(True),
    )

    await extraction_worker._process_one(SpyDriver(), str(kg_id), source, chunk_index)

    assert merge_called == []
    assert _read_status(config.task_queue_db_path(), str(kg_id), source, chunk_index) == "completed"


@pytest.mark.asyncio
async def test_process_one_llm_error_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_id = uuid4()
    kg_folder, doc_folder, source, chunk_index = await _seed_pending_chunk(tmp_path, kg_id)

    _patch_kg_repo(monkeypatch, _make_kg(kg_id, str(kg_folder)))
    monkeypatch.setattr(
        "services.extraction_worker.get_llm_provider",
        lambda: FakeLLM(error=RuntimeError("LLM 逾時")),
    )
    monkeypatch.setattr("services.extraction_worker.get_embedding_provider", _raise_runtime_error)

    await extraction_worker._process_one(SpyDriver(), str(kg_id), source, chunk_index)

    assert _read_status(config.task_queue_db_path(), str(kg_id), source, chunk_index) == "failed"
    updated_record = document_record_service.read_record(doc_folder)
    assert updated_record.extraction_status == "failed"
    assert updated_record.chunk_progress == 0  # 失敗不推進進度
    assert updated_record.completed_chunk_indices == []


@pytest.mark.asyncio
async def test_process_one_missing_kg_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_id = uuid4()
    _patch_kg_repo(monkeypatch, None)

    task_queue_service.enqueue(config.task_queue_db_path(), str(kg_id), "note.md", [1])

    await extraction_worker._process_one(SpyDriver(), str(kg_id), "note.md", 1)

    assert _read_status(config.task_queue_db_path(), str(kg_id), "note.md", 1) == "failed"


@pytest.mark.asyncio
async def test_process_one_missing_chunk_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    kg_id = uuid4()
    _patch_kg_repo(monkeypatch, _make_kg(kg_id, str(kg_folder)))
    task_queue_service.enqueue(config.task_queue_db_path(), str(kg_id), "missing.md", [1])

    await extraction_worker._process_one(SpyDriver(), str(kg_id), "missing.md", 1)

    assert _read_status(config.task_queue_db_path(), str(kg_id), "missing.md", 1) == "failed"


@pytest.mark.asyncio
async def test_run_extraction_worker_processes_pending_then_idles_until_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    db_path = config.task_queue_db_path()
    task_queue_service.enqueue(db_path, "kg-1", "note.md", [1])

    processed = []

    async def _fake_process_one(driver, kg_id, source, chunk_index):
        processed.append((kg_id, source, chunk_index))
        task_queue_service.update_status(db_path, kg_id, source, chunk_index, "completed")

    monkeypatch.setattr("services.extraction_worker._process_one", _fake_process_one)

    task = asyncio.create_task(
        extraction_worker.run_extraction_worker(SpyDriver(), poll_interval_idle=0.01)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert processed == [("kg-1", "note.md", 1)]
