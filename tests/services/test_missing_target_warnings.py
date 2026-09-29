import logging
import sqlite3

import pytest

from services import document_record_service as records
from services import task_queue_service as queue
from state.task_sm import TaskStatus as StateTaskStatus


@pytest.mark.parametrize(
    ("function_name", "call"),
    [
        (
            "set_svo_chunk_total",
            lambda folder: records.set_svo_chunk_total(folder, 3),
        ),
        (
            "reset_extraction_progress",
            lambda folder: records.reset_extraction_progress(folder),
        ),
        (
            "record_chunk_completed",
            lambda folder: records.record_chunk_completed(folder, 1),
        ),
        (
            "mark_extraction_failed",
            lambda folder: records.mark_extraction_failed(folder),
        ),
        (
            "update_normalization_progress",
            lambda folder: records.update_normalization_progress(
                folder, status="processing", progress=1, total_sentences=2,
            ),
        ),
    ],
)
def test_document_record_missing_writes_log_one_warning_each(
    tmp_path, caplog, function_name, call,
):
    missing = tmp_path / "missing-record"
    caplog.set_level(logging.WARNING)

    assert call(missing) is None
    assert not missing.exists()

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert function_name in warnings[0].message
    assert str(missing) in warnings[0].message


def test_update_status_missing_row_logs_warning_and_returns_none(tmp_path, caplog):
    db_path = tmp_path / "task_queue.db"
    kg_id = "kg-x3a"
    source = "missing.md"
    chunk_index = 7
    caplog.set_level(logging.WARNING)

    assert queue.update_status(db_path, kg_id, source, chunk_index, "completed") is None

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM task_queue WHERE kg_id=? AND source=? AND chunk_index=?",
            (kg_id, source, chunk_index),
        ).fetchone()
    assert row is None

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].message
    assert kg_id in message
    assert source in message
    assert str(chunk_index) in message
    assert "completed" in message
    assert "TaskStatus." not in message


def test_update_status_existing_row_logs_nothing(tmp_path, caplog):
    db_path = tmp_path / "task_queue.db"
    queue.enqueue(db_path, "kg-x3a", "existing.md", [1])
    caplog.set_level(logging.WARNING)

    queue.update_status(db_path, "kg-x3a", "existing.md", 1, "processing")
    queue.update_status(
        db_path,
        "kg-x3a",
        "existing.md",
        1,
        StateTaskStatus.COMPLETED,
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM task_queue WHERE kg_id=? AND source=? AND chunk_index=?",
            ("kg-x3a", "existing.md", 1),
        ).fetchone()
    assert row == ("completed",)
    assert not [record for record in caplog.records if record.levelno == logging.WARNING]


def test_document_record_existing_writes_log_nothing(tmp_path, caplog):
    records.init_record(tmp_path, source="existing.md", total_chunks=3)
    caplog.set_level(logging.WARNING)

    results = [
        records.set_svo_chunk_total(tmp_path, 3),
        records.reset_extraction_progress(tmp_path),
        records.record_chunk_completed(tmp_path, 1),
        records.mark_extraction_failed(tmp_path),
        records.update_normalization_progress(
            tmp_path, status="processing", progress=1, total_sentences=2,
        ),
    ]

    assert all(result is not None for result in results)
    assert not [record for record in caplog.records if record.levelno == logging.WARNING]


def test_set_document_vector_missing_record_stays_silent(tmp_path, caplog):
    missing = tmp_path / "missing-vector-record"
    caplog.set_level(logging.WARNING)

    assert records.set_document_vector(missing, [0.1, 0.2, 0.3]) is None
    assert not missing.exists()
    assert not [record for record in caplog.records if record.levelno == logging.WARNING]
