from pathlib import Path
from uuid import uuid4

import pytest

from services import classify_service as svc
from services import document_record_service


class FakeEmbeddingProvider:
    """確定性假 embedding provider：文字 → 向量的對照表，讓測試結果可預測。"""

    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping

    @property
    def dim(self) -> int:
        return 3

    def encode(self, text: str) -> list[float]:
        return self.mapping.get(text, [0.0, 0.0, 0.0])

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


def _write_chunk(doc_folder: Path, idx: int, total: int, body: str) -> None:
    doc_folder.mkdir(parents=True, exist_ok=True)
    content = f'---\nsource: "x"\nchunk_index: {idx}\ntotal_chunks: {total}\n---\n\n{body}\n'
    (doc_folder / f"chunk-{idx:03d}-of-{total:03d}.md").write_text(content, encoding="utf-8")


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        assert svc.cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert svc.cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_zero_vector_returns_zero_not_divide_error(self):
        assert svc.cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0


class TestMeanVector:
    def test_averages_each_dimension(self):
        assert svc.mean_vector([[1, 2, 3], [3, 4, 5]]) == pytest.approx([2, 3, 4])

    def test_empty_list_returns_none(self):
        assert svc.mean_vector([]) is None


class TestComputeDocumentVector:
    def test_averages_chunk_vectors(self, tmp_path, monkeypatch):
        doc_folder = tmp_path / "report"
        _write_chunk(doc_folder, 1, 2, "第一段")
        _write_chunk(doc_folder, 2, 2, "第二段")

        fake = FakeEmbeddingProvider({"第一段": [1.0, 0.0, 0.0], "第二段": [0.0, 1.0, 0.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        assert svc.compute_document_vector(doc_folder) == pytest.approx([0.5, 0.5, 0.0])

    def test_empty_folder_returns_none(self, tmp_path, monkeypatch):
        doc_folder = tmp_path / "empty_doc"
        doc_folder.mkdir()
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: FakeEmbeddingProvider({}))
        assert svc.compute_document_vector(doc_folder) is None


class TestComputeKgPrototype:
    def test_averages_member_document_vectors(self, tmp_path, monkeypatch):
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "doc1", 1, 1, "A")
        _write_chunk(kg_folder / "doc2", 1, 1, "B")

        fake = FakeEmbeddingProvider({"A": [1.0, 0.0], "B": [0.0, 1.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        assert svc.compute_kg_prototype(kg_folder) == pytest.approx([0.5, 0.5])

    def test_nonexistent_kg_folder_returns_none(self, tmp_path):
        assert svc.compute_kg_prototype(tmp_path / "does_not_exist") is None


class TestClassifyByVector:
    def test_scores_above_min_threshold_get_matched(self):
        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=Path("/x"))
        result = svc.classify_by_vector("doc", [1.0, 0.0], {kg: [1.0, 0.0]})

        assert result.status == "pending"
        assert result.matched_kg_id == kg.kg_id
        assert result.score == pytest.approx(1.0)

    def test_below_min_threshold_excluded_from_candidates(self):
        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=Path("/x"))
        result = svc.classify_by_vector("doc", [1.0, 0.0], {kg: [0.0, 1.0]}, min_threshold=0.05)

        assert result.status == "unmatched"
        assert result.candidates == []

    def test_none_document_vector_returns_unmatched(self):
        assert svc.classify_by_vector("doc", None, {}).status == "unmatched"

    def test_candidates_sorted_by_score_descending(self):
        kg1 = svc.KGInfo(uuid4(), "KG-1", Path("/x"))
        kg2 = svc.KGInfo(uuid4(), "KG-2", Path("/y"))
        result = svc.classify_by_vector(
            "doc", [1.0, 0.0],
            {kg1: [0.6, 0.8], kg2: [1.0, 0.0]},
            min_threshold=0.0,
        )

        assert [c.kg_name for c in result.candidates] == ["KG-2", "KG-1"]
        assert result.matched_kg_name == "KG-2"

    def test_kg_with_no_prototype_is_skipped(self):
        kg1 = svc.KGInfo(uuid4(), "KG-1", Path("/x"))
        kg2 = svc.KGInfo(uuid4(), "KG-2", Path("/y"))
        result = svc.classify_by_vector("doc", [1.0, 0.0], {kg1: None, kg2: [1.0, 0.0]}, min_threshold=0.0)

        assert len(result.candidates) == 1
        assert result.matched_kg_name == "KG-2"


class TestAssignDocumentToKg:
    def test_moves_folder_and_records_assignment_history(self, tmp_path):
        staging_doc = tmp_path / "staging" / "report"
        _write_chunk(staging_doc, 1, 1, "內容")
        kg_folder = tmp_path / "kg_a"
        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=kg_folder)

        dest = svc.assign_document_to_kg(staging_doc, kg, method="manual")

        assert dest == kg_folder / "report"
        assert dest.exists()
        assert not staging_doc.exists()

        record = document_record_service.read_record(dest)
        assert len(record.assignment_history) == 1
        assert record.assignment_history[0].kg_id == kg.kg_id
        assert record.assignment_history[0].method == "manual"


class TestComputeDocumentVectorCaching:
    def test_uses_cached_vector_from_record_without_calling_provider(self, tmp_path, monkeypatch):
        doc_folder = tmp_path / "report"
        _write_chunk(doc_folder, 1, 1, "內容")
        document_record_service.init_record(doc_folder, source="report", total_chunks=1)
        document_record_service.set_document_vector(doc_folder, [9.0, 9.0, 9.0])

        def _boom():
            raise AssertionError("不應呼叫 embedding provider，應直接使用快取")
        monkeypatch.setattr(svc, "get_embedding_provider", _boom)

        assert svc.compute_document_vector(doc_folder) == [9.0, 9.0, 9.0]

    def test_computes_and_caches_when_record_exists_but_uncached(self, tmp_path, monkeypatch):
        doc_folder = tmp_path / "report"
        _write_chunk(doc_folder, 1, 1, "第一段")
        document_record_service.init_record(doc_folder, source="report", total_chunks=1)

        fake = FakeEmbeddingProvider({"第一段": [1.0, 0.0, 0.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        result = svc.compute_document_vector(doc_folder)

        assert result == pytest.approx([1.0, 0.0, 0.0])
        assert document_record_service.read_record(doc_folder).document_vector == pytest.approx([1.0, 0.0, 0.0])

    def test_no_record_file_computes_without_caching(self, tmp_path, monkeypatch):
        doc_folder = tmp_path / "report"
        _write_chunk(doc_folder, 1, 1, "第一段")  # 刻意不呼叫 init_record

        fake = FakeEmbeddingProvider({"第一段": [1.0, 0.0, 0.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        result = svc.compute_document_vector(doc_folder)

        assert result == pytest.approx([1.0, 0.0, 0.0])
        assert document_record_service.read_record(doc_folder) is None


class TestComputeKgPrototypeCaching:
    def test_cache_hit_skips_recomputation(self, tmp_path, monkeypatch):
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "doc1", 1, 1, "A")

        fake = FakeEmbeddingProvider({"A": [1.0, 0.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        first = svc.compute_kg_prototype(kg_folder)
        assert (kg_folder / "_prototype_cache.json").exists()

        def _boom():
            raise AssertionError("成員清單未變，應直接命中快取，不應重新計算")
        monkeypatch.setattr(svc, "get_embedding_provider", _boom)

        assert svc.compute_kg_prototype(kg_folder) == first

    def test_cache_invalidated_when_membership_changes(self, tmp_path, monkeypatch):
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "doc1", 1, 1, "A")

        fake = FakeEmbeddingProvider({"A": [1.0, 0.0], "B": [0.0, 1.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)
        svc.compute_kg_prototype(kg_folder)

        _write_chunk(kg_folder / "doc2", 1, 1, "B")

        assert svc.compute_kg_prototype(kg_folder) == pytest.approx([0.5, 0.5])


class TestCountKgMembers:
    def test_counts_only_directories(self, tmp_path):
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "doc1", 1, 1, "A")
        _write_chunk(kg_folder / "doc2", 1, 1, "B")
        (kg_folder / "_prototype_cache.json").write_text("{}", encoding="utf-8")

        assert svc.count_kg_members(kg_folder) == 2

    def test_nonexistent_folder_returns_zero(self, tmp_path):
        assert svc.count_kg_members(tmp_path / "missing") == 0


class TestClassifyByVectorLowConfidence:
    def test_flags_low_confidence_when_member_count_below_min_cluster_size(self):
        kg = svc.KGInfo(uuid4(), "KG-A", Path("/x"))
        result = svc.classify_by_vector("doc", [1.0, 0.0], {kg: [1.0, 0.0]}, kg_member_counts={kg: 1})

        assert result.candidates[0].member_count == 1
        assert result.candidates[0].low_confidence is True

    def test_no_flag_when_member_count_meets_min_cluster_size(self):
        kg = svc.KGInfo(uuid4(), "KG-A", Path("/x"))
        result = svc.classify_by_vector(
            "doc", [1.0, 0.0], {kg: [1.0, 0.0]}, kg_member_counts={kg: svc.CLUSTER_MIN_SIZE},
        )

        assert result.candidates[0].low_confidence is False

    def test_no_flag_when_member_counts_not_provided(self):
        kg = svc.KGInfo(uuid4(), "KG-A", Path("/x"))
        result = svc.classify_by_vector("doc", [1.0, 0.0], {kg: [1.0, 0.0]})

        assert result.candidates[0].low_confidence is False


class TestIncrementalPrototypeUpdate:
    def test_first_member_returns_vector_itself(self):
        assert svc._incremental_prototype_update(None, 0, [1.0, 2.0]) == [1.0, 2.0]

    def test_averages_with_existing_prototype_weighted_by_count(self):
        result = svc._incremental_prototype_update([0.0, 0.0], 2, [3.0, 3.0])
        assert result == pytest.approx([1.0, 1.0])


class TestAssignDocumentToKgRollback:
    def test_rolls_back_move_when_record_update_fails(self, tmp_path, monkeypatch):
        staging_doc = tmp_path / "staging" / "report"
        _write_chunk(staging_doc, 1, 1, "內容")
        kg_folder = tmp_path / "kg_a"
        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=kg_folder)

        def _boom(*args, **kwargs):
            raise RuntimeError("模擬記錄檔寫入失敗")
        monkeypatch.setattr(document_record_service, "append_assignment", _boom)

        with pytest.raises(RuntimeError):
            svc.assign_document_to_kg(staging_doc, kg, method="manual")

        assert staging_doc.exists()
        assert not (kg_folder / "report").exists()


class TestClassifyAll:
    def test_auto_assigns_when_score_clears_threshold(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        _write_chunk(staging / "report", 1, 1, "A")
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "existing_doc", 1, 1, "A")

        fake = FakeEmbeddingProvider({"A": [1.0, 0.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=kg_folder)
        results = svc.classify_all(staging, [kg], auto_assign=True, auto_threshold=0.3)

        assert results[0].status == "assigned"
        assert results[0].auto_assigned is True
        assert not (staging / "report").exists()
        assert (kg_folder / "report").exists()

    def test_leaves_unmatched_documents_in_staging_pool(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        _write_chunk(staging / "unrelated", 1, 1, "Z")
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "existing_doc", 1, 1, "A")

        fake = FakeEmbeddingProvider({"A": [1.0, 0.0], "Z": [0.0, 1.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=kg_folder)
        results = svc.classify_all(staging, [kg], auto_assign=True, auto_threshold=0.3)

        assert results[0].status == "unmatched"
        assert (staging / "unrelated").exists()

    def test_below_auto_threshold_stays_pending_not_auto_assigned(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        _write_chunk(staging / "report", 1, 1, "A")
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "existing_doc", 1, 1, "B")

        # A vs B 相似度介於 min_threshold 與 auto_threshold 之間（非 0 非 1）
        fake = FakeEmbeddingProvider({"A": [1.0, 0.2], "B": [0.2, 1.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=kg_folder)
        results = svc.classify_all(staging, [kg], auto_assign=True, auto_threshold=0.9)

        assert results[0].status == "pending"
        assert results[0].auto_assigned is False
        assert (staging / "report").exists()

    def test_empty_staging_folder_returns_empty_list(self, tmp_path):
        assert svc.classify_all(tmp_path / "does_not_exist", []) == []

    def test_prototype_and_member_count_update_within_batch(self, tmp_path, monkeypatch):
        """batch 內第一份文件自動分配後，同批次第二份文件比對時應立即看到
        member_count 已加一，而不是拿整批共用、批次開始時算好的舊值。"""
        staging = tmp_path / "staging"
        _write_chunk(staging / "doc_a", 1, 1, "A")
        _write_chunk(staging / "doc_b", 1, 1, "A")
        kg_folder = tmp_path / "kg_a"
        _write_chunk(kg_folder / "seed", 1, 1, "A")

        fake = FakeEmbeddingProvider({"A": [1.0, 0.0]})
        monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake)

        kg = svc.KGInfo(kg_id=uuid4(), kg_name="KG-A", folder_path=kg_folder)
        results = svc.classify_all(staging, [kg], auto_assign=True, auto_threshold=0.3)

        assert results[0].auto_assigned is True
        assert results[0].candidates[0].member_count == 1
        assert results[1].candidates[0].member_count == 2
