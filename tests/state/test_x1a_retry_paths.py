from datetime import datetime, timezone
from uuid import uuid4

import pytest

from models.knowledge_graph import KnowledgeGraph
from services import document_record_service as records
from services import knowledge_graph_service as graph
from services import task_queue_service as queue


def _queue_status(db_path, kg_id, source, chunk_index):
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM task_queue WHERE kg_id = ? AND source = ? AND chunk_index = ?",
            (kg_id, source, chunk_index),
        ).fetchone()
    return row[0] if row else None


def _failed_middle_chunk(tmp_path):
    kg_id = "kg-1"
    source = "doc.md"
    kg_folder = tmp_path / kg_id
    doc_folder = kg_folder / source
    doc_folder.mkdir(parents=True)
    records.init_record(doc_folder, source=source, total_chunks=3)
    records.set_svo_chunk_total(doc_folder, 3)
    db_path = tmp_path / "task_queue.db"
    queue.enqueue(db_path, kg_id, source, [1, 2, 3])

    records.record_chunk_completed(doc_folder, 1)
    queue.update_status(db_path, kg_id, source, 1, "completed")
    records.mark_extraction_failed(doc_folder)
    queue.update_status(db_path, kg_id, source, 2, "failed")
    records.record_chunk_completed(doc_folder, 3)
    queue.update_status(db_path, kg_id, source, 3, "completed")
    return kg_id, source, kg_folder, doc_folder, db_path


def test_partial_success_after_failure_keeps_failed(tmp_path):
    kg_id, source, _kg_folder, doc_folder, db_path = _failed_middle_chunk(tmp_path)

    record = records.read_record(doc_folder)
    assert record.extraction_status == "failed"
    assert sorted(record.completed_chunk_indices) == [1, 3]
    assert _queue_status(db_path, kg_id, source, 2) == "failed"


def test_retry_via_enqueue_recovers_to_completed(tmp_path):
    kg_id, source, _kg_folder, doc_folder, db_path = _failed_middle_chunk(tmp_path)

    queue.enqueue(db_path, kg_id, source, [2])
    assert _queue_status(db_path, kg_id, source, 2) == "pending"
    records.record_chunk_completed(doc_folder, 2)
    queue.update_status(db_path, kg_id, source, 2, "completed")

    record = records.read_record(doc_folder)
    assert record.extraction_status == "completed"
    assert sorted(record.completed_chunk_indices) == [1, 2, 3]


def test_retry_via_rebuild_from_records_recovers_to_completed(tmp_path):
    kg_id, source, kg_folder, doc_folder, db_path = _failed_middle_chunk(tmp_path)

    db_path.unlink()
    queue.rebuild_from_records(db_path, {kg_id: kg_folder})
    assert _queue_status(db_path, kg_id, source, 2) == "pending"
    records.record_chunk_completed(doc_folder, 2)
    queue.update_status(db_path, kg_id, source, 2, "completed")

    assert records.read_record(doc_folder).extraction_status == "completed"


def test_trusted_restart_leaves_existing_failed_queue_row(tmp_path):
    kg_id, source, kg_folder, doc_folder, db_path = _failed_middle_chunk(tmp_path)

    queue.ensure_ready(db_path, {kg_id: kg_folder})

    assert _queue_status(db_path, kg_id, source, 2) == "failed"
    assert queue.next_pending(db_path, kg_id) is None
    assert records.read_record(doc_folder).extraction_status == "failed"


@pytest.mark.asyncio
async def test_build_graph_does_not_skip_failed_documents(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    doc_folder = kg_folder / "doc.md"
    doc_folder.mkdir(parents=True)
    records.init_record(doc_folder, source="doc.md", total_chunks=1)
    records.set_svo_chunk_total(doc_folder, 1)
    records.mark_extraction_failed(doc_folder)

    kg = KnowledgeGraph(
        id=uuid4(),
        name="test",
        description="",
        folder_path=str(kg_folder),
        is_public=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class FakeRepo:
        def __init__(self, driver):
            self.driver = driver

        async def get(self, kg_id):
            return kg if kg_id == kg.id else None

    triggered = []

    async def fake_trigger(driver, folder, kg_id):
        triggered.append((folder, kg_id))

    monkeypatch.setattr(graph, "KGRepository", FakeRepo)
    monkeypatch.setattr(graph.svo_service, "trigger_extraction", fake_trigger)
    await graph.build_graph(object(), kg.id, force_rebuild=False)

    assert triggered == [(doc_folder, kg.id)]


def test_reset_and_reassign_still_clear_failed(tmp_path):
    reset_folder = tmp_path / "reset"
    records.init_record(reset_folder, source="reset.md", total_chunks=1)
    records.mark_extraction_failed(reset_folder)
    records.reset_extraction_progress(reset_folder)
    assert records.read_record(reset_folder).extraction_status == "pending"

    reassign_folder = tmp_path / "reassign"
    records.init_record(reassign_folder, source="reassign.md", total_chunks=1)
    records.mark_extraction_failed(reassign_folder)
    records.append_assignment(reassign_folder, uuid4(), "retry", "manual")
    assert records.read_record(reassign_folder).extraction_status == "pending"
