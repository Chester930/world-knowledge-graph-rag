from uuid import uuid4

import pytest

from services import document_record_service, task_queue_service as svc


def _db_path(tmp_path):
    return tmp_path / "task_queue.db"


class TestEnqueueAndStatus:
    def test_enqueue_registers_pending_chunks(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2, 3])

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 1)

    def test_enqueue_is_idempotent_and_does_not_overwrite_existing_status(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2])
        svc.update_status(db_path, "kg-1", "doc.txt", 1, "processing")

        # 重新登記同一批 chunk（模擬重啟後再次 ENQUEUE），不應把已在處理中的
        # chunk 1 覆寫回 pending
        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2])

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 2)

    def test_update_status_transitions_through_five_states(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1])

        for status in ["processing", "pending_upload", "completed"]:
            svc.update_status(db_path, "kg-1", "doc.txt", 1, status)

        assert svc.next_pending(db_path, "kg-1") is None


class TestNextPending:
    def test_orders_by_chunk_index_ascending(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [3, 1, 2])

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 1)

    def test_returns_none_when_queue_empty(self, tmp_path):
        db_path = _db_path(tmp_path)
        assert svc.next_pending(db_path, "kg-1") is None

    def test_searches_across_all_kg_when_kg_id_omitted(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-2", "doc-b.txt", [5])
        svc.enqueue(db_path, "kg-1", "doc-a.txt", [1])

        assert svc.next_pending(db_path) == ("kg-1", "doc-a.txt", 1)

    def test_scoped_kg_id_ignores_other_kg_pending_items(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-2", "doc-b.txt", [1])

        assert svc.next_pending(db_path, "kg-1") is None


class TestInterruptionHandling:
    def test_reset_stuck_processing_reverts_to_pending(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2])
        svc.update_status(db_path, "kg-1", "doc.txt", 1, "processing")
        svc.update_status(db_path, "kg-1", "doc.txt", 2, "completed")

        affected = svc.reset_stuck_processing(db_path)

        assert affected == 1
        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 1)


class TestTrustAndRebuild:
    def test_missing_db_is_not_trustworthy(self, tmp_path):
        assert svc.is_index_trustworthy(_db_path(tmp_path)) is False

    def test_valid_db_is_trustworthy(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1])
        assert svc.is_index_trustworthy(db_path) is True

    def test_corrupted_db_is_not_trustworthy(self, tmp_path):
        db_path = _db_path(tmp_path)
        db_path.write_text("this is not a sqlite file", encoding="utf-8")
        assert svc.is_index_trustworthy(db_path) is False

    def test_rebuild_scans_document_records_for_pending_chunks(self, tmp_path):
        db_path = _db_path(tmp_path)
        kg_folder = tmp_path / "kg-1"
        doc_folder = kg_folder / "doc-a"
        doc_folder.mkdir(parents=True)
        document_record_service.init_record(doc_folder, source="doc-a.txt", total_chunks=5)
        document_record_service.update_normalization_progress(
            doc_folder, status="completed", progress=5, total_sentences=5,
        )
        document_record_service.set_svo_chunk_total(doc_folder, 3)

        svc.rebuild_from_records(db_path, {"kg-1": kg_folder})

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc-a.txt", 1)

    def test_rebuild_skips_completed_documents(self, tmp_path):
        db_path = _db_path(tmp_path)
        kg_folder = tmp_path / "kg-1"
        doc_folder = kg_folder / "doc-a"
        doc_folder.mkdir(parents=True)
        record = document_record_service.init_record(doc_folder, source="doc-a.txt", total_chunks=2)
        document_record_service.append_assignment(doc_folder, kg_id=uuid4(), kg_name="KG-1", method="manual")
        document_record_service.set_svo_chunk_total(doc_folder, 2)
        # 手動標記為已完成（模擬 3.1.4 DONE4 之後的狀態；3.1.4 尚未實作對外
        # 的公開 setter，此處直接呼叫模組內部寫入函式供測試設置初始狀態）
        record = document_record_service.read_record(doc_folder)
        record.extraction_status = "completed"
        document_record_service._write_record(doc_folder, record)

        svc.rebuild_from_records(db_path, {"kg-1": kg_folder})

        assert svc.next_pending(db_path, "kg-1") is None

    def test_rebuild_removes_stale_db_before_rescanning(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-old", "stale.txt", [1, 2, 3])

        svc.rebuild_from_records(db_path, {})

        assert svc.next_pending(db_path) is None


class TestEnsureReady:
    def test_ensure_ready_resets_processing_when_index_trustworthy(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1])
        svc.update_status(db_path, "kg-1", "doc.txt", 1, "processing")

        svc.ensure_ready(db_path, kg_folders={})

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 1)

    def test_ensure_ready_rebuilds_when_index_missing(self, tmp_path):
        db_path = _db_path(tmp_path)
        kg_folder = tmp_path / "kg-1"
        doc_folder = kg_folder / "doc-a"
        doc_folder.mkdir(parents=True)
        document_record_service.init_record(doc_folder, source="doc-a.txt", total_chunks=1)
        document_record_service.set_svo_chunk_total(doc_folder, 1)

        svc.ensure_ready(db_path, kg_folders={"kg-1": kg_folder})

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc-a.txt", 1)
