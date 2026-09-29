"""STATUS: characterization only, not wired (P1 batch 1).

This module records the current task-queue behavior from reports 120 and 121;
it is not an idealized state machine and is not imported by production code.
"""
from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_UPLOAD = "pending_upload"


class TaskEvent(StrEnum):
    ENQUEUE = "enqueue"
    CLAIM = "claim"
    RESET_STUCK = "reset_stuck"
    RECONCILE_INSERT = "reconcile_insert"
    SET_STATUS = "set_status"


TASK_TRANSITIONS: dict[
    tuple[TaskStatus | None, TaskEvent], TaskStatus | None
] = {
    (None, TaskEvent.ENQUEUE): TaskStatus.PENDING,
    (TaskStatus.PENDING, TaskEvent.ENQUEUE): TaskStatus.PENDING,
    (TaskStatus.PROCESSING, TaskEvent.ENQUEUE): TaskStatus.PROCESSING,
    (TaskStatus.COMPLETED, TaskEvent.ENQUEUE): TaskStatus.PENDING,
    (TaskStatus.FAILED, TaskEvent.ENQUEUE): TaskStatus.PENDING,
    (TaskStatus.PENDING_UPLOAD, TaskEvent.ENQUEUE): TaskStatus.PENDING_UPLOAD,
    (None, TaskEvent.CLAIM): None,
    (TaskStatus.PENDING, TaskEvent.CLAIM): TaskStatus.PROCESSING,
    (TaskStatus.PROCESSING, TaskEvent.CLAIM): TaskStatus.PROCESSING,
    (TaskStatus.COMPLETED, TaskEvent.CLAIM): TaskStatus.COMPLETED,
    (TaskStatus.FAILED, TaskEvent.CLAIM): TaskStatus.FAILED,
    (TaskStatus.PENDING_UPLOAD, TaskEvent.CLAIM): TaskStatus.PENDING_UPLOAD,
    (None, TaskEvent.RESET_STUCK): None,
    (TaskStatus.PENDING, TaskEvent.RESET_STUCK): TaskStatus.PENDING,
    (TaskStatus.PROCESSING, TaskEvent.RESET_STUCK): TaskStatus.PENDING,
    (TaskStatus.COMPLETED, TaskEvent.RESET_STUCK): TaskStatus.COMPLETED,
    (TaskStatus.FAILED, TaskEvent.RESET_STUCK): TaskStatus.FAILED,
    (TaskStatus.PENDING_UPLOAD, TaskEvent.RESET_STUCK): TaskStatus.PENDING_UPLOAD,
    (None, TaskEvent.RECONCILE_INSERT): TaskStatus.PENDING,
    (TaskStatus.PENDING, TaskEvent.RECONCILE_INSERT): TaskStatus.PENDING,
    (TaskStatus.PROCESSING, TaskEvent.RECONCILE_INSERT): TaskStatus.PROCESSING,
    (TaskStatus.COMPLETED, TaskEvent.RECONCILE_INSERT): TaskStatus.COMPLETED,
    (TaskStatus.FAILED, TaskEvent.RECONCILE_INSERT): TaskStatus.FAILED,
    (TaskStatus.PENDING_UPLOAD, TaskEvent.RECONCILE_INSERT): TaskStatus.PENDING_UPLOAD,
}


def task_next_status(
    current: TaskStatus | None,
    event: TaskEvent,
    target: TaskStatus | None = None,
) -> TaskStatus | None:
    if event is TaskEvent.SET_STATUS:
        # 既有行為（報告120 X3）：不存在的 row 靜默 no-op，另案再修。
        if current is None:
            return None
        if target is None:
            raise ValueError("SET_STATUS requires target")
        return target
    return TASK_TRANSITIONS[(current, event)]
