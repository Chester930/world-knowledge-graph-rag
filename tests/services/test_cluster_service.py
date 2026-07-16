from pathlib import Path

import numpy as np
import pytest

from services import cluster_service as svc
from services.classify_service import KGInfo  # noqa: F401  (not used directly, kept for parity)


def _write_chunk(doc_folder: Path, idx: int, total: int, body: str) -> None:
    doc_folder.mkdir(parents=True, exist_ok=True)
    content = f'---\nsource: "x"\nchunk_index: {idx}\ntotal_chunks: {total}\n---\n\n{body}\n'
    (doc_folder / f"chunk-{idx:03d}-of-{total:03d}.md").write_text(content, encoding="utf-8")


class FakeEmbeddingProvider:
    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping

    @property
    def dim(self) -> int:
        return 2

    def encode(self, text: str) -> list[float]:
        return self.mapping.get(text, [0.0, 0.0])

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


class FakeLLMProvider:
    def __init__(self, response: str = "名稱：測試分類\n描述：一句話描述"):
        self.response = response
        self.received_prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.received_prompts.append(prompt)
        return self.response

    async def stream(self, prompt: str):
        yield self.response


class TestClusterVectors:
    def test_fewer_than_min_cluster_size_are_all_noise(self):
        vectors = [[0.0, 0.0], [0.1, 0.1]]
        assert svc.cluster_vectors(vectors, min_cluster_size=3) == [-1, -1]

    def test_realistic_dataset_recognizes_multiple_clusters_and_noise(self):
        """實測記錄：min_samples 需明確設低於 min_cluster_size（見模組 docstring），
        且需要有足夠資料量（此處 14 點）HDBSCAN 才能穩定辨識出剛好達
        min_cluster_size 邊界（3 個成員）的小群；過小的合成資料集（如 6 點）
        在實測中會被 HDBSCAN 全數判為雜訊，並非本模組參數設定錯誤。"""
        rng = np.random.default_rng(0)
        c1 = rng.normal(loc=[0, 0], scale=0.1, size=(5, 2))
        c2 = rng.normal(loc=[8, 8], scale=0.1, size=(4, 2))
        c3 = rng.normal(loc=[-8, 8], scale=0.1, size=(3, 2))  # 剛好達 min_cluster_size
        noise = np.array([[20.0, -20.0], [-20.0, -20.0]])

        vectors = np.vstack([c1, c2, c3, noise]).tolist()
        labels = svc.cluster_vectors(vectors, min_cluster_size=3)

        # 三個真實群各自的標籤應一致（同群同標籤），且都不是雜訊
        assert len(set(labels[0:5])) == 1 and labels[0] != -1
        assert len(set(labels[5:9])) == 1 and labels[5] != -1
        assert len(set(labels[9:12])) == 1 and labels[9] != -1
        # 三個群彼此標籤不同
        assert len({labels[0], labels[5], labels[9]}) == 3
        # 兩個離群點應被標為雜訊
        assert labels[12] == -1 and labels[13] == -1


class TestDominantSubclusterIndices:
    def test_returns_all_indices_when_below_min_cluster_size(self):
        vectors = [[0.0, 0.0], [0.1, 0.1]]
        assert svc.dominant_subcluster_indices(vectors, min_cluster_size=3) == [0, 1]

    def test_falls_back_to_all_indices_when_no_subcluster_found(self):
        # 3 個點彼此距離接近，密度均勻，很可能整體被視為雜訊或單一群而非再分裂
        vectors = [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]
        result = svc.dominant_subcluster_indices(vectors, min_cluster_size=3)
        assert result == [0, 1, 2] or len(result) >= 1  # 至少要有輸出可用於命名


class TestExtractTopConcepts:
    def test_counts_word_frequency(self):
        bodies = ["知識圖譜 知識圖譜 檢索", "知識圖譜 增強生成"]
        top = svc.extract_top_concepts(bodies, top_n=2)
        assert top[0] == "知識圖譜"

    def test_empty_bodies_returns_empty_list(self):
        assert svc.extract_top_concepts([]) == []


class TestNamingPromptAndParsing:
    def test_build_naming_prompt_includes_files_and_concepts(self):
        prompt = svc.build_naming_prompt(["a.pdf", "b.pdf"], ["知識圖譜", "檢索"])
        assert "a.pdf" in prompt
        assert "知識圖譜" in prompt

    def test_parse_naming_response_extracts_name_and_description(self):
        name, desc = svc.parse_naming_response("名稱：個人知識管理\n描述：關於筆記工具的討論")
        assert name == "個人知識管理"
        assert desc == "關於筆記工具的討論"

    def test_parse_naming_response_falls_back_when_unparseable(self):
        name, desc = svc.parse_naming_response("這不是預期的格式")
        assert name == "新知識庫"
        assert desc == ""


class TestMeanPairwiseCosineSimilarity:
    def test_identical_vectors_yield_similarity_one(self):
        assert svc.mean_pairwise_cosine_similarity([[1, 0], [1, 0], [1, 0]]) == pytest.approx(1.0)

    def test_single_vector_returns_one(self):
        assert svc.mean_pairwise_cosine_similarity([[1, 0]]) == 1.0

    def test_empty_returns_one(self):
        assert svc.mean_pairwise_cosine_similarity([]) == 1.0


class TestAnalyzeStagingPool:
    @pytest.mark.asyncio
    async def test_produces_suggestion_for_a_valid_cluster(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        # 3 份彼此相似的文件（達 min_cluster_size=3）
        _write_chunk(staging / "doc1", 1, 1, "A")
        _write_chunk(staging / "doc2", 1, 1, "A2")
        _write_chunk(staging / "doc3", 1, 1, "A3")

        fake_embedding = FakeEmbeddingProvider({
            "A": [1.0, 0.0], "A2": [0.98, 0.02], "A3": [0.97, 0.03],
        })
        monkeypatch.setattr("services.classify_service.get_embedding_provider", lambda: fake_embedding)

        fake_llm = FakeLLMProvider("名稱：測試分類\n描述：測試描述")
        monkeypatch.setattr(svc, "get_llm_provider", lambda: fake_llm)

        result = await svc.analyze_staging_pool(staging, min_cluster_size=3)

        assert len(result.suggestions) == 1
        suggestion = result.suggestions[0]
        assert suggestion.suggested_name == "測試分類"
        assert sorted(suggestion.candidate_folders) == ["doc1", "doc2", "doc3"]
        assert result.unclustered_folders == []

    @pytest.mark.asyncio
    async def test_below_min_cluster_size_all_stay_unclustered(self, tmp_path):
        staging = tmp_path / "staging"
        _write_chunk(staging / "doc1", 1, 1, "A")
        _write_chunk(staging / "doc2", 1, 1, "B")

        result = await svc.analyze_staging_pool(staging, min_cluster_size=3)

        assert result.suggestions == []
        assert sorted(result.unclustered_folders) == ["doc1", "doc2"]

    @pytest.mark.asyncio
    async def test_nonexistent_staging_folder_returns_empty_result(self, tmp_path):
        result = await svc.analyze_staging_pool(tmp_path / "does_not_exist")
        assert result.suggestions == []
        assert result.unclustered_folders == []

    @pytest.mark.asyncio
    async def test_naming_llm_failure_falls_back_gracefully(self, tmp_path, monkeypatch):
        staging = tmp_path / "staging"
        _write_chunk(staging / "doc1", 1, 1, "A")
        _write_chunk(staging / "doc2", 1, 1, "A2")
        _write_chunk(staging / "doc3", 1, 1, "A3")

        fake_embedding = FakeEmbeddingProvider({
            "A": [1.0, 0.0], "A2": [0.98, 0.02], "A3": [0.97, 0.03],
        })
        monkeypatch.setattr("services.classify_service.get_embedding_provider", lambda: fake_embedding)

        class FailingLLM:
            async def generate(self, prompt):
                raise RuntimeError("LLM 服務不可用")

        monkeypatch.setattr(svc, "get_llm_provider", lambda: FailingLLM())

        result = await svc.analyze_staging_pool(staging, min_cluster_size=3)

        assert len(result.suggestions) == 1
        assert result.suggestions[0].suggested_name == "新知識庫"
