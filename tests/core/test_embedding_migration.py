from __future__ import annotations

import json

import numpy as np
import pytest

from core.config import Settings
from core.constants import VECTOR_DIM
from core.providers.embedding.ollama import OllamaEmbeddingProvider
from core.vector_migration import clear_stale_vector_caches, migrate_vector_indexes


def test_shipped_embedding_defaults_are_bge_m3_1024_without_env_overrides():
    settings = Settings(_env_file=None)

    assert settings.ollama_embedding_model == "bge-m3"
    assert settings.local_embedding_model == "BAAI/bge-m3"
    assert VECTOR_DIM == 1024


def test_clear_stale_vector_caches_removes_old_npy_and_prototype_cache(tmp_path):
    old_npy = tmp_path / "baseline_rag_index_old_cs500.npy"
    old_json = tmp_path / "baseline_rag_index_old_cs500.json"
    np.save(old_npy, np.zeros((2, 384), dtype=np.float32))
    old_json.write_text("[]", encoding="utf-8")

    old_prototype = tmp_path / "_prototype_cache.json"
    old_prototype.write_text(
        json.dumps({"prototype": [0.0] * 384}), encoding="utf-8"
    )
    current_npy = tmp_path / "baseline_rag_index_current_cs500.npy"
    np.save(current_npy, np.zeros((2, VECTOR_DIM), dtype=np.float32))

    removed = clear_stale_vector_caches(tmp_path)

    assert old_npy in removed
    assert old_json in removed
    assert old_prototype in removed
    assert not old_npy.exists()
    assert not old_json.exists()
    assert not old_prototype.exists()
    assert current_npy.exists()


def test_ollama_probe_failure_falls_back_to_bge_m3_dimension(monkeypatch):
    def fail_post(*args, **kwargs):
        raise OSError("ollama offline")

    monkeypatch.setattr("core.providers.embedding.ollama.httpx.post", fail_post)

    provider = OllamaEmbeddingProvider("http://localhost:11434", "bge-m3")

    assert provider.dim == VECTOR_DIM


@pytest.mark.asyncio
async def test_migrate_vector_indexes_drops_legacy_and_wrong_dimensions():
    class Driver:
        def __init__(self):
            self.calls = []

        async def execute_query(self, query, **params):
            self.calls.append((query, params))
            if query.startswith("SHOW VECTOR INDEXES"):
                return type("Result", (), {"records": [
                    {"name": "concept_embedding_idx", "options": {
                        "indexConfig": {"vector.dimensions": 1024}
                    }},
                    {"name": "chunk_embedding_vector", "options": {
                        "indexConfig": {"vector.dimensions": 384}
                    }},
                    {"name": "related_to_verb_embedding", "options": {
                        "indexConfig": {"vector.dimensions": 1024}
                    }},
                ]})()
            return type("Result", (), {"records": []})()

    driver = Driver()

    removed = await migrate_vector_indexes(
        driver, obsolete_index_names=("concept_embedding_idx",)
    )

    assert removed == ["concept_embedding_idx", "chunk_embedding_vector"]
    assert any("DROP INDEX concept_embedding_idx IF EXISTS" in query for query, _ in driver.calls)
    assert any("DROP INDEX chunk_embedding_vector IF EXISTS" in query for query, _ in driver.calls)
    assert not any("DROP INDEX related_to_verb_embedding" in query for query, _ in driver.calls)
