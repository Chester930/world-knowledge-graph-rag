import json
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

    def test_enqueue_resets_terminal_status_back_to_pending(self, tmp_path):
        """2026-08-25 修復：`build_graph(force_rebuild=True)` 清空 Neo4j 圖譜
        資料＋重設記錄檔進度後，重新呼叫 `trigger_extraction()` 必須真的能
        再次排入佇列——先前卡在 `completed`／`failed` 的組合會被舊版
        `INSERT OR IGNORE` 靜默忽略，導致圖譜資料已清空但佇列仍認為完成，
        Worker 永遠不會重新處理。"""
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2])
        svc.update_status(db_path, "kg-1", "doc.txt", 1, "completed")
        svc.update_status(db_path, "kg-1", "doc.txt", 2, "failed")

        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2])

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 1)
        svc.update_status(db_path, "kg-1", "doc.txt", 1, "completed")
        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 2)

    def test_enqueue_still_protects_in_flight_status(self, tmp_path):
        """終態才重置為 pending；`processing`／`pending_upload` 仍受既有保護，
        不因重新 ENQUEUE 被誤重置——與上一則修復同一次變更，確認未破壞
        既有保護語意。"""
        db_path = _db_path(tmp_path)
        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2])
        svc.update_status(db_path, "kg-1", "doc.txt", 1, "processing")
        svc.update_status(db_path, "kg-1", "doc.txt", 2, "pending_upload")

        svc.enqueue(db_path, "kg-1", "doc.txt", [1, 2])

        assert svc.next_pending(db_path, "kg-1") is None

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

        assert affected == [("kg-1", "doc.txt", 1)]
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

    def test_rebuild_uses_svo_index_json_for_non_contiguous_chunk_indices(self, tmp_path):
        """對應 commit 5909c4c 的修復意圖：svo chunk index 並非一定從 1 連續
        編號時，應直接採用 `svo_index.json` 記錄的實際 index 清單，而非用
        `chunk_progress+1..total` 推算出查無此 index 的假性待處理項目。"""
        db_path = _db_path(tmp_path)
        kg_folder = tmp_path / "kg-1"
        doc_folder = kg_folder / "doc-a"
        doc_folder.mkdir(parents=True)
        document_record_service.init_record(doc_folder, source="doc-a.txt", total_chunks=5)
        document_record_service.set_svo_chunk_total(doc_folder, 3)
        (doc_folder / "svo_index.json").write_text(
            json.dumps({"source": "doc-a.txt", "total_svo_chunks": 3, "chunks": [
                {"index": 2}, {"index": 5}, {"index": 7},  # 刻意非連續、不從 1 開始
            ]}),
            encoding="utf-8",
        )

        svc.rebuild_from_records(db_path, {"kg-1": kg_folder})

        registered = set()
        while (item := svc.next_pending(db_path, "kg-1")) is not None:
            registered.add(item[2])
            svc.update_status(db_path, "kg-1", "doc-a.txt", item[2], "completed")
        assert registered == {2, 5, 7}

    def test_rebuild_requeues_gap_left_by_out_of_order_completion(self, tmp_path):
        """迴歸測試（2026-08-19）：chunk 3 從未完成（例如失敗），但編號更大的
        chunk 5 已完成——`completed_chunk_indices` 只會有 {1,2,4,5}。REBUILD
        必須依這個實際完成集合判斷缺口，只補登記真正缺席的 3，而不是誤用
        `chunk_progress`（=5，看過的最大值）以為 1..5 全數完成而漏登記。"""
        db_path = _db_path(tmp_path)
        kg_folder = tmp_path / "kg-1"
        doc_folder = kg_folder / "doc-a"
        doc_folder.mkdir(parents=True)
        document_record_service.init_record(doc_folder, source="doc-a.txt", total_chunks=5)
        document_record_service.set_svo_chunk_total(doc_folder, 5)
        document_record_service.record_chunk_completed(doc_folder, 1)
        document_record_service.record_chunk_completed(doc_folder, 2)
        document_record_service.record_chunk_completed(doc_folder, 4)
        document_record_service.record_chunk_completed(doc_folder, 5)
        (doc_folder / "svo_index.json").write_text(
            json.dumps({"source": "doc-a.txt", "total_svo_chunks": 5, "chunks": [
                {"index": 1}, {"index": 2}, {"index": 3}, {"index": 4}, {"index": 5},
            ]}),
            encoding="utf-8",
        )
        record = document_record_service.read_record(doc_folder)
        assert record.extraction_status == "processing"  # 尚未被誤判為 completed

        svc.rebuild_from_records(db_path, {"kg-1": kg_folder})

        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc-a.txt", 3)

    def test_rebuild_falls_back_to_range_when_svo_index_json_missing(self, tmp_path):
        """2026-08-18 迴歸修復：REBUILD 本身就是索引檔案已遺失/損毀時的救援
        路徑——`svo_index.json` 若剛好也缺席，不該靜默跳過整份文件（會讓
        待處理進度悄悄消失），應退回範圍推算，寧可誤登記幾個查無此 index
        的項目（worker 端可重試）。"""
        db_path = _db_path(tmp_path)
        kg_folder = tmp_path / "kg-1"
        doc_folder = kg_folder / "doc-a"
        doc_folder.mkdir(parents=True)
        document_record_service.init_record(doc_folder, source="doc-a.txt", total_chunks=5)
        document_record_service.set_svo_chunk_total(doc_folder, 3)
        # 刻意不寫 svo_index.json，模擬索引檔案本身也缺席的情境

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

        reset_chunks = svc.ensure_ready(db_path, kg_folders={})

        assert reset_chunks == [("kg-1", "doc.txt", 1)]
        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc.txt", 1)

    def test_ensure_ready_rebuilds_when_index_missing(self, tmp_path):
        db_path = _db_path(tmp_path)
        kg_folder = tmp_path / "kg-1"
        doc_folder = kg_folder / "doc-a"
        doc_folder.mkdir(parents=True)
        document_record_service.init_record(doc_folder, source="doc-a.txt", total_chunks=1)
        document_record_service.set_svo_chunk_total(doc_folder, 1)

        reset_chunks = svc.ensure_ready(db_path, kg_folders={"kg-1": kg_folder})

        # REBUILD 分支無法精確得知哪些 chunk 中斷於寫入中途，回傳空清單
        # （見 ensure_ready() docstring 誠實聲明），不是遺漏。
        assert reset_chunks == []
        assert svc.next_pending(db_path, "kg-1") == ("kg-1", "doc-a.txt", 1)
