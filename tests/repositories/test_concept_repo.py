from __future__ import annotations

import pytest

from repositories.concept_repo import ConceptRepository


class _Result:
    def __init__(self, records):
        self.records = records


class _Driver:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, **params):
        self.calls.append((query, params))
        if "SHOW VECTOR INDEXES" in query:
            return _Result([
                {"name": "concept_embedding_idx", "options": {
                    "indexConfig": {"vector.dimensions": 384}
                }},
            ])
        return _Result([])


@pytest.mark.asyncio
async def test_create_vector_index_migrates_legacy_384_index_to_1024():
    driver = _Driver()

    await ConceptRepository(driver).create_vector_index()

    assert any("DROP INDEX concept_embedding_idx IF EXISTS" in query for query, _ in driver.calls)
    create_query, create_params = next(
        (query, params) for query, params in driver.calls
        if "CREATE VECTOR INDEX concept_q_vector" in query
    )
    assert "vector.dimensions" in create_query
    assert create_params["dim"] == 1024
