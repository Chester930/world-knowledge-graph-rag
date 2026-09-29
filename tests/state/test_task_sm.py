import json
import sqlite3

import pytest

from services import document_record_service
from services import task_queue_service as svc
from state.task_sm import TASK_TRANSITIONS, TaskEvent, TaskStatus, task_next_status


def _db_path(tmp_path, name="task_queue.db"):
    return tmp_path / name


def _row_status(db_path, chunk_index=1, source="doc.md"):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM task_queue WHERE kg_id=? AND source=? AND chunk_index=?",
            ("kg-1", source, chunk_index),
        ).fetchone()
    return None if row is None else TaskStatus(row[0])


def _create_record_for_reconcile(tmp_path, name):
    kg_folder = tmp_path / f"kg-{name}"
    doc_folder = kg_folder / "doc"
    doc_folder.mkdir(parents=True)
    document_record_service.init_record(doc_folder, source="doc.md", total_chunks=1)
    document_record_service.set_svo_chunk_total(doc_folder, 1)
    (doc_folder / "svo_index.json").write_text(
        json.dumps({"source": "doc.md", "total_svo_chunks": 1, "chunks": [{"index": 1}]}),
        encoding="utf-8",
    )
    return doc_folder


def _set_queue_source(db_path, current):
    svc.enqueue(db_path, "kg-1", "doc.md", [1])
    if current is not None:
        svc.update_status(db_path, "kg-1", "doc.md", 1, current.value)


def test_task_enum_values_match_service_literal():
    assert {status.value for status in TaskStatus} == set(
        __import__("typing").get_args(svc.TaskStatus)
    )


def test_task_table_is_complete():
    expected_events = {
        TaskEvent.ENQUEUE,
        TaskEvent.CLAIM,
        TaskEvent.RESET_STUCK,
        TaskEvent.RECONCILE_INSERT,
    }
    expected = {
        (status, event)
        for status in [None, *TaskStatus]
        for event in expected_events
    }
    assert len(TASK_TRANSITIONS) == 24
    assert set(TASK_TRANSITIONS) == expected


@pytest.mark.parametrize("current", [None, *TaskStatus])
@pytest.mark.parametrize(
    "event",
    [TaskEvent.ENQUEUE, TaskEvent.CLAIM, TaskEvent.RESET_STUCK, TaskEvent.RECONCILE_INSERT],
)
def test_task_sm_parity_with_real_functions(tmp_path, current, event):
    db_path = _db_path(tmp_path, f"{event.value}-{current or 'missing'}.db")
    if event is TaskEvent.RECONCILE_INSERT:
        doc_folder = _create_record_for_reconcile(tmp_path, f"{event.value}-{current or 'missing'}")
        _set_queue_source(db_path, current)
        with svc._connect(db_path) as conn:
            svc._reconcile_doc(conn, "kg-1", doc_folder)
            conn.commit()
    else:
        if current is not None:
            _set_queue_source(db_path, current)
        if event is TaskEvent.ENQUEUE:
            svc.enqueue(db_path, "kg-1", "doc.md", [1])
        elif event is TaskEvent.CLAIM:
            svc.claim_next_pending(db_path, "kg-1")
        elif event is TaskEvent.RESET_STUCK:
            svc.reset_stuck_processing(db_path)

    assert _row_status(db_path) == task_next_status(current, event)


@pytest.mark.parametrize("current", list(TaskStatus))
@pytest.mark.parametrize("target", list(TaskStatus))
def test_set_status_accepts_any_transition_on_existing_row(tmp_path, current, target):
    db_path = _db_path(tmp_path, f"set-{current.value}-{target.value}.db")
    _set_queue_source(db_path, current)
    svc.update_status(db_path, "kg-1", "doc.md", 1, target.value)

    assert _row_status(db_path) == task_next_status(current, TaskEvent.SET_STATUS, target)


def test_set_status_on_missing_row_is_silent_noop(tmp_path):
    db_path = _db_path(tmp_path)
    svc.update_status(db_path, "kg-1", "doc.md", 1, "completed")

    assert _row_status(db_path) is None
    assert task_next_status(None, TaskEvent.SET_STATUS, TaskStatus.COMPLETED) is None


def test_claim_and_reset_on_absent_row(tmp_path):
    claim_db = _db_path(tmp_path, "claim.db")
    reset_db = _db_path(tmp_path, "reset.db")

    assert svc.claim_next_pending(claim_db, "kg-1") is None
    assert svc.reset_stuck_processing(reset_db) == []
    assert task_next_status(None, TaskEvent.CLAIM) is None
    assert task_next_status(None, TaskEvent.RESET_STUCK) is None
