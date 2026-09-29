from typing import get_args
from uuid import uuid4

import pytest

from models.knowledge_graph import DocumentRecord
from services import document_record_service as svc
from state.document_sm import (
    DOCUMENT_TRANSITIONS,
    DocumentEvent,
    ExtractionStatus,
    NormalizationEvent,
    NormalizationStatus,
    document_next_status,
    normalization_next_status,
)


def _record_with_extraction_status(tmp_path, status: ExtractionStatus, name: str):
    folder = tmp_path / name
    svc.init_record(folder, source=f"{name}.md", total_chunks=3)
    record = svc.read_record(folder)
    record.extraction_status = status.value
    svc._write_record(folder, record)
    return folder


def _record_with_normalization_status(tmp_path, status: NormalizationStatus, name: str):
    folder = tmp_path / name
    svc.init_record(folder, source=f"{name}.md", total_chunks=1)
    record = svc.read_record(folder)
    record.normalization_status = status.value
    svc._write_record(folder, record)
    return folder


def test_enum_values_match_model_literals():
    extraction_annotation = DocumentRecord.model_fields["extraction_status"].annotation
    normalization_annotation = DocumentRecord.model_fields["normalization_status"].annotation

    assert {status.value for status in ExtractionStatus} == set(get_args(extraction_annotation))
    assert {status.value for status in NormalizationStatus} == set(get_args(normalization_annotation))


def test_document_table_is_complete():
    expected = {
        (status, event)
        for status in ExtractionStatus
        for event in DocumentEvent
    }
    assert len(DOCUMENT_TRANSITIONS) == 25
    assert set(DOCUMENT_TRANSITIONS) == expected


@pytest.mark.parametrize("current", list(ExtractionStatus))
@pytest.mark.parametrize("event", list(DocumentEvent))
def test_document_sm_parity_with_real_functions(tmp_path, current, event):
    folder = _record_with_extraction_status(tmp_path, current, f"{current.value}-{event.value}")

    if event is DocumentEvent.RESET:
        svc.reset_extraction_progress(folder)
    elif event is DocumentEvent.REASSIGN:
        svc.append_assignment(folder, uuid4(), "parity", "manual")
    elif event is DocumentEvent.CHUNK_COMPLETED_PARTIAL:
        svc.set_svo_chunk_total(folder, 3)
        svc.record_chunk_completed(folder, 1)
    elif event is DocumentEvent.CHUNK_COMPLETED_FULL:
        svc.set_svo_chunk_total(folder, 3)
        svc.record_chunk_completed(folder, 1)
        svc.record_chunk_completed(folder, 2)
        svc.record_chunk_completed(folder, 3)
    elif event is DocumentEvent.MARK_FAILED:
        svc.mark_extraction_failed(folder)

    observed = ExtractionStatus(svc.read_record(folder).extraction_status)
    assert observed == document_next_status(current, event)


def test_failed_stays_failed_on_partial_completion(tmp_path):
    """報告130 X1 已於報告133 修復：部分完成不再洗回 processing。"""
    folder = _record_with_extraction_status(tmp_path, ExtractionStatus.FAILED, "x1")
    svc.set_svo_chunk_total(folder, 3)
    svc.mark_extraction_failed(folder)
    svc.record_chunk_completed(folder, 1)

    observed = ExtractionStatus(svc.read_record(folder).extraction_status)
    assert observed is ExtractionStatus.FAILED
    assert observed is document_next_status(
        ExtractionStatus.FAILED, DocumentEvent.CHUNK_COMPLETED_PARTIAL
    )


@pytest.mark.parametrize("current", list(NormalizationStatus))
@pytest.mark.parametrize("target", list(NormalizationStatus))
def test_normalization_parity(tmp_path, current, target):
    folder = _record_with_normalization_status(tmp_path, current, f"{current.value}-{target.value}")
    svc.update_normalization_progress(folder, status=target.value, progress=0)

    observed = NormalizationStatus(svc.read_record(folder).normalization_status)
    assert observed == normalization_next_status(current, NormalizationEvent.SET_STATUS, target)


@pytest.mark.parametrize("current", list(NormalizationStatus))
def test_normalization_reparse_resets_to_not_started(tmp_path, current):
    folder = _record_with_normalization_status(tmp_path, current, f"reparse-{current.value}")
    record = svc.read_record(folder)
    record.total_chunks = 1
    svc._write_record(folder, record)

    svc.init_record(folder, source="reparsed.md", total_chunks=2)

    observed = NormalizationStatus(svc.read_record(folder).normalization_status)
    assert observed == normalization_next_status(
        current, NormalizationEvent.REPARSE_CHUNK_COUNT_CHANGED
    )


def test_missing_record_writes_are_silent_noops(tmp_path):
    missing = tmp_path / "missing"
    calls = [
        lambda: svc.record_chunk_completed(missing, 1),
        lambda: svc.mark_extraction_failed(missing),
        lambda: svc.set_svo_chunk_total(missing, 3),
        lambda: svc.reset_extraction_progress(missing),
        lambda: svc.update_normalization_progress(
            missing, status="processing", progress=0,
        ),
    ]

    for call in calls:
        assert call() is None
    assert not missing.exists()


def test_next_status_requires_target():
    with pytest.raises(ValueError):
        normalization_next_status(
            NormalizationStatus.NOT_STARTED, NormalizationEvent.SET_STATUS
        )
