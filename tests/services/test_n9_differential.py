"""N9 G1／G2 搬移差分測試（報告168 W1）：搬移後的程式對 golden（搬移前實作產生）逐案比對。"""

import json

import pytest

from tests.services.n9_differential_harness import GOLDEN, run_all


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual():
    from services import svo_service

    return run_all(svo_service)


def test_at_least_1000_cases_per_function(golden):
    from collections import Counter

    c = Counter(g["kind"] for g in golden)
    for name in ("_rrf_fuse_fact_ids", "_filter_fact_candidates_by_source_scope", "_apply_source_doc_cap",
                 "_dedupe_facts_by_key", "_bfs_pass_cypher", "_bfs_records_to_triples"):
        assert c[name] >= 1000, name


def test_same_case_list_shape(golden, actual):
    assert [(g["kind"], g["args"]) for g in golden] == [(a["kind"], a["args"]) for a in actual]


def test_every_case_result_identical(golden, actual):
    diffs = [(i, g["kind"]) for i, (g, a) in enumerate(zip(golden, actual)) if g["res"] != a["res"]]
    assert not diffs, f"{len(diffs)} 案不一致，前幾筆：{diffs[:5]}"
