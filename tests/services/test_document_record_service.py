from uuid import uuid4

from services import document_record_service as svc


def test_init_record_creates_fresh_record_when_missing(tmp_path):
    record = svc.init_record(tmp_path, source="report.pdf", total_chunks=5)

    assert record.source == "report.pdf"
    assert record.total_chunks == 5
    assert record.assignment_history == []
    assert record.extraction_status == "pending"
    assert record.chunk_progress == 0
    assert (tmp_path / "_record.json").exists()


def test_init_record_is_idempotent_and_preserves_existing_history(tmp_path):
    kg_id = uuid4()
    svc.init_record(tmp_path, source="report.pdf", total_chunks=5)
    svc.append_assignment(tmp_path, kg_id=kg_id, kg_name="KG-A", method="auto")

    # 模擬文件內容更新後重新解析：total_chunks 改變，但不應抹除歸屬歷史
    record = svc.init_record(tmp_path, source="report.pdf", total_chunks=7)

    assert record.total_chunks == 7
    assert len(record.assignment_history) == 1
    assert record.assignment_history[0].kg_id == kg_id


def test_read_record_returns_none_when_missing(tmp_path):
    assert svc.read_record(tmp_path) is None


def test_append_assignment_records_history_entry(tmp_path):
    kg_id = uuid4()
    svc.init_record(tmp_path, source="report.pdf", total_chunks=3)

    record = svc.append_assignment(tmp_path, kg_id=kg_id, kg_name="個人知識管理工具", method="manual")

    assert len(record.assignment_history) == 1
    entry = record.assignment_history[0]
    assert entry.kg_id == kg_id
    assert entry.kg_name == "個人知識管理工具"
    assert entry.method == "manual"
    assert entry.assigned_at is not None


def test_append_assignment_resets_extraction_progress_on_reassignment(tmp_path):
    """依 § 3.1.2 定案：重新歸屬時一律重設抽取狀態，不沿用舊 KG 的抽取進度。"""
    kg_a, kg_b = uuid4(), uuid4()
    svc.init_record(tmp_path, source="report.pdf", total_chunks=10)

    record = svc.read_record(tmp_path)
    record.extraction_status = "completed"
    record.chunk_progress = 10
    svc._write_record(tmp_path, record)

    reassigned = svc.append_assignment(tmp_path, kg_id=kg_b, kg_name="KG-B", method="manual")

    assert reassigned.extraction_status == "pending"
    assert reassigned.chunk_progress == 0
    assert len(reassigned.assignment_history) == 1
    assert reassigned.assignment_history[0].kg_id == kg_b


def test_append_assignment_accumulates_multiple_history_entries(tmp_path):
    kg_a, kg_b = uuid4(), uuid4()
    svc.init_record(tmp_path, source="report.pdf", total_chunks=3)

    svc.append_assignment(tmp_path, kg_id=kg_a, kg_name="KG-A", method="auto")
    record = svc.append_assignment(tmp_path, kg_id=kg_b, kg_name="KG-B", method="manual")

    assert [e.kg_id for e in record.assignment_history] == [kg_a, kg_b]


def test_append_assignment_creates_record_if_folder_has_none_yet(tmp_path):
    kg_id = uuid4()
    record = svc.append_assignment(tmp_path, kg_id=kg_id, kg_name="KG-A", method="auto")

    assert len(record.assignment_history) == 1
    assert (tmp_path / "_record.json").exists()


def test_write_record_is_atomic_and_does_not_leave_tmp_files(tmp_path):
    svc.init_record(tmp_path, source="report.pdf", total_chunks=1)

    tmp_files = list(tmp_path.glob(".*_record.json*.tmp"))
    assert tmp_files == []


def test_set_document_vector_caches_into_existing_record(tmp_path):
    svc.init_record(tmp_path, source="report.pdf", total_chunks=1)

    updated = svc.set_document_vector(tmp_path, [0.1, 0.2, 0.3])

    assert updated.document_vector == [0.1, 0.2, 0.3]
    assert svc.read_record(tmp_path).document_vector == [0.1, 0.2, 0.3]


def test_set_document_vector_no_op_when_record_missing(tmp_path):
    assert svc.set_document_vector(tmp_path, [0.1, 0.2, 0.3]) is None
    assert svc.read_record(tmp_path) is None


def test_init_record_clears_cached_vector_when_total_chunks_changes(tmp_path):
    svc.init_record(tmp_path, source="report.pdf", total_chunks=5)
    svc.set_document_vector(tmp_path, [0.1, 0.2, 0.3])
    svc.update_normalization_progress(
        tmp_path, status="completed", progress=10, total_sentences=10,
    )
    svc.set_svo_chunk_total(tmp_path, 4)

    # 模擬文件內容重新解析、切塊數改變：先前快取的向量已不代表目前內容
    record = svc.init_record(tmp_path, source="report.pdf", total_chunks=7)

    assert record.document_vector is None
    assert record.normalization_status == "not_started"
    assert record.normalization_progress == 0
    assert record.normalization_total_sentences == 0
    assert record.svo_total_chunks == 0


def test_init_record_keeps_cached_vector_when_total_chunks_unchanged(tmp_path):
    svc.init_record(tmp_path, source="report.pdf", total_chunks=5)
    svc.set_document_vector(tmp_path, [0.1, 0.2, 0.3])

    record = svc.init_record(tmp_path, source="report.pdf", total_chunks=5)

    assert record.document_vector == [0.1, 0.2, 0.3]


def test_update_normalization_progress_persists_checkpoint(tmp_path):
    svc.init_record(tmp_path, source="report.pdf", total_chunks=1)

    record = svc.update_normalization_progress(
        tmp_path, status="processing", progress=3, total_sentences=10,
    )

    assert record.normalization_status == "processing"
    assert record.normalization_progress == 3
    assert record.normalization_total_sentences == 10
    assert svc.read_record(tmp_path).normalization_progress == 3


def test_update_normalization_progress_no_op_when_record_missing(tmp_path):
    assert svc.update_normalization_progress(
        tmp_path, status="processing", progress=1, total_sentences=2,
    ) is None


def test_set_svo_chunk_total_persists_separate_from_rag_chunks(tmp_path):
    svc.init_record(tmp_path, source="report.pdf", total_chunks=9)

    record = svc.set_svo_chunk_total(tmp_path, 3)

    assert record.total_chunks == 9
    assert record.svo_total_chunks == 3
