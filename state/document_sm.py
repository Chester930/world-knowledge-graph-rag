"""STATUS: characterization only, not wired (P1 batch 1).

This module records the current behavior described by reports 120 and 121;
it is not an idealized state machine and is not imported by production code.
In particular, X1 (``failed -> processing``) is existing behavior.
"""
from __future__ import annotations

from enum import StrEnum


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_UPLOAD = "pending_upload"


class DocumentEvent(StrEnum):
    RESET = "reset"
    REASSIGN = "reassign"
    CHUNK_COMPLETED_PARTIAL = "chunk_completed_partial"
    CHUNK_COMPLETED_FULL = "chunk_completed_full"
    MARK_FAILED = "mark_failed"


DOCUMENT_TRANSITIONS: dict[tuple[ExtractionStatus, DocumentEvent], ExtractionStatus] = {
    (ExtractionStatus.PENDING, DocumentEvent.RESET): ExtractionStatus.PENDING,
    (ExtractionStatus.PENDING, DocumentEvent.REASSIGN): ExtractionStatus.PENDING,
    (ExtractionStatus.PENDING, DocumentEvent.CHUNK_COMPLETED_PARTIAL): ExtractionStatus.PROCESSING,
    (ExtractionStatus.PENDING, DocumentEvent.CHUNK_COMPLETED_FULL): ExtractionStatus.COMPLETED,
    (ExtractionStatus.PENDING, DocumentEvent.MARK_FAILED): ExtractionStatus.FAILED,
    (ExtractionStatus.PROCESSING, DocumentEvent.RESET): ExtractionStatus.PENDING,
    (ExtractionStatus.PROCESSING, DocumentEvent.REASSIGN): ExtractionStatus.PENDING,
    (ExtractionStatus.PROCESSING, DocumentEvent.CHUNK_COMPLETED_PARTIAL): ExtractionStatus.PROCESSING,
    (ExtractionStatus.PROCESSING, DocumentEvent.CHUNK_COMPLETED_FULL): ExtractionStatus.COMPLETED,
    (ExtractionStatus.PROCESSING, DocumentEvent.MARK_FAILED): ExtractionStatus.FAILED,
    (ExtractionStatus.COMPLETED, DocumentEvent.RESET): ExtractionStatus.PENDING,
    (ExtractionStatus.COMPLETED, DocumentEvent.REASSIGN): ExtractionStatus.PENDING,
    (ExtractionStatus.COMPLETED, DocumentEvent.CHUNK_COMPLETED_PARTIAL): ExtractionStatus.PROCESSING,
    (ExtractionStatus.COMPLETED, DocumentEvent.CHUNK_COMPLETED_FULL): ExtractionStatus.COMPLETED,
    (ExtractionStatus.COMPLETED, DocumentEvent.MARK_FAILED): ExtractionStatus.FAILED,
    (ExtractionStatus.FAILED, DocumentEvent.RESET): ExtractionStatus.PENDING,
    (ExtractionStatus.FAILED, DocumentEvent.REASSIGN): ExtractionStatus.PENDING,
    # 既有行為（報告120 X1）：failed → processing，另案再修。
    (ExtractionStatus.FAILED, DocumentEvent.CHUNK_COMPLETED_PARTIAL): ExtractionStatus.PROCESSING,
    # 同一低階函式也允許 failed → completed，依現況保留。
    (ExtractionStatus.FAILED, DocumentEvent.CHUNK_COMPLETED_FULL): ExtractionStatus.COMPLETED,
    (ExtractionStatus.FAILED, DocumentEvent.MARK_FAILED): ExtractionStatus.FAILED,
    (ExtractionStatus.PENDING_UPLOAD, DocumentEvent.RESET): ExtractionStatus.PENDING,
    (ExtractionStatus.PENDING_UPLOAD, DocumentEvent.REASSIGN): ExtractionStatus.PENDING,
    (ExtractionStatus.PENDING_UPLOAD, DocumentEvent.CHUNK_COMPLETED_PARTIAL): ExtractionStatus.PROCESSING,
    (ExtractionStatus.PENDING_UPLOAD, DocumentEvent.CHUNK_COMPLETED_FULL): ExtractionStatus.COMPLETED,
    (ExtractionStatus.PENDING_UPLOAD, DocumentEvent.MARK_FAILED): ExtractionStatus.FAILED,
}


def document_next_status(current: ExtractionStatus, event: DocumentEvent) -> ExtractionStatus:
    return DOCUMENT_TRANSITIONS[(current, event)]


class NormalizationStatus(StrEnum):
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class NormalizationEvent(StrEnum):
    SET_STATUS = "set_status"
    REPARSE_CHUNK_COUNT_CHANGED = "reparse_chunk_count_changed"


NORMALIZATION_TRANSITIONS: dict[
    tuple[NormalizationStatus, NormalizationEvent], NormalizationStatus
] = {
    (NormalizationStatus.NOT_STARTED, NormalizationEvent.REPARSE_CHUNK_COUNT_CHANGED): NormalizationStatus.NOT_STARTED,
    (NormalizationStatus.PROCESSING, NormalizationEvent.REPARSE_CHUNK_COUNT_CHANGED): NormalizationStatus.NOT_STARTED,
    (NormalizationStatus.COMPLETED, NormalizationEvent.REPARSE_CHUNK_COUNT_CHANGED): NormalizationStatus.NOT_STARTED,
    (NormalizationStatus.FAILED, NormalizationEvent.REPARSE_CHUNK_COUNT_CHANGED): NormalizationStatus.NOT_STARTED,
}


def normalization_next_status(
    current: NormalizationStatus,
    event: NormalizationEvent,
    target: NormalizationStatus | None = None,
) -> NormalizationStatus:
    if event is NormalizationEvent.SET_STATUS:
        if target is None:
            raise ValueError("SET_STATUS requires target")
        return target
    return NORMALIZATION_TRANSITIONS[(current, event)]
