from pathlib import Path

import pytest

from services import document_record_service, ingestion_service as svc


class TestChunkAndStage:
    def test_writes_chunks_and_initializes_record(self, tmp_path):
        staging = tmp_path / "staging"
        text = "第一句。" * 200  # 遠超過 chunk_size=500，確保產生多個切塊

        doc_folder, record = svc.chunk_and_stage(text, "report.txt", staging)

        assert doc_folder == staging / "report"
        assert doc_folder.exists()
        chunk_files = sorted(doc_folder.glob("chunk-*-of-*.md"))
        assert len(chunk_files) == record.total_chunks
        assert record.total_chunks > 1
        assert record.source == "report.txt"
        assert record.extraction_status == "pending"
        assert record.assignment_history == []

        # 原始解析文字（切塊前）另存一份，供 SVO 抽取獨立的切塊/標準化流程使用，
        # 避免需要時得重新解析原始上傳檔案。
        original_file = doc_folder / "original.md"
        assert original_file.exists()
        assert text in original_file.read_text(encoding="utf-8")

    def test_record_file_matches_folder_state(self, tmp_path):
        staging = tmp_path / "staging"
        doc_folder, record = svc.chunk_and_stage("這是一段測試內容。另一句。", "note.md", staging)

        on_disk = document_record_service.read_record(doc_folder)
        assert on_disk == record

    def test_empty_text_raises_and_creates_no_folder(self, tmp_path):
        staging = tmp_path / "staging"

        with pytest.raises(ValueError):
            svc.chunk_and_stage("", "empty.txt", staging)

        assert not (staging / "empty").exists()

    def test_blank_source_raises(self, tmp_path):
        staging = tmp_path / "staging"

        with pytest.raises(ValueError):
            svc.chunk_and_stage("有內容。", "   ", staging)

    def test_reprocessing_same_source_preserves_assignment_history(self, tmp_path):
        """重複呼叫同一 source（模擬內容更新後重新上傳）：切塊檔案更新，但既有
        歸屬歷史（若已被分類過）不應被抹除——驗證與 document_record_service 既有
        行為（見 § 3.1.1／3.1.2）正確銜接。"""
        staging = tmp_path / "staging"
        doc_folder, _ = svc.chunk_and_stage("第一版內容。" * 5, "report.txt", staging)

        from uuid import uuid4
        document_record_service.append_assignment(
            doc_folder, kg_id=uuid4(), kg_name="KG-A", method="manual",
        )

        _, updated_record = svc.chunk_and_stage("完全不同的第二版內容，長度也不一樣。" * 30, "report.txt", staging)

        assert len(updated_record.assignment_history) == 1
        assert updated_record.assignment_history[0].kg_name == "KG-A"
        assert updated_record.total_chunks > 1
