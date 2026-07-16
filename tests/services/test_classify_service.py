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
