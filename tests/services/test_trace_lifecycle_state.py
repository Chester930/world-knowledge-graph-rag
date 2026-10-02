"""報告258 L1：檢索 trace 顯示 Fact 生命週期狀態（只讀只顯示、零行為變更；假 driver，不連 Neo4j）。"""
import ast
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services import relation_lifecycle  # 僅測試檔匯入：漂移比對（報告258 T2）
from services import semantic_marks as sm
from services import svo_service as svc
from services.context.telemetry import build_retrieval_trace

REPO = Path(__file__).resolve().parents[2]


# ---- T1／T2 ---------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, sm.PENDING), ("", sm.PENDING), ("   ", sm.PENDING),
    *[(s, s) for s in ("候選", "有效", "已被取代", "已終止", "爭議", "已駁回")],
    (" 有效 ", "有效"),
    ("亂值", sm.UNKNOWN), (123, sm.UNKNOWN), (0, sm.UNKNOWN), (["有效"], sm.UNKNOWN), (True, sm.UNKNOWN),
])
def test_mark_lifecycle_state(value, expected):
    assert sm.mark_lifecycle_state(value) == expected


def test_lifecycle_states_do_not_drift_from_relation_lifecycle_and_marks_unchanged():
    assert set(sm.LIFECYCLE_STATES) == set(relation_lifecycle.CORE_STATES)
    assert len(sm.LIFECYCLE_STATES) == len(set(sm.LIFECYCLE_STATES)) == 6
    assert sm.MARKS == (sm.RESOLVED, sm.NOT_APPLICABLE, sm.UNKNOWN, sm.PENDING, sm.INDETERMINATE)


# ---- T4 / 5-1, 5-2 -------------------------------------------------------

def _facts(**extra):
    return [
        {"fact_text": "甲 規定 乙", "subject": "甲", "object": "乙", "verb": "規定", "rel_type": "REGULATES",
         "score": 0.9, "source_doc_id": "d1", "source_svo_chunk_index": 2, "article_no": "第3條", **extra},
    ]


GOLDEN_OFF_FACT = {
    "kind": "fact", "rank": 0, "text": "甲 規定 乙", "score": 0.9, "source_doc_id": "d1",
    "source_svo_chunk_index": 2, "article_no": "第3條", "in_prompt": None,
}


def test_flag_off_golden_snapshot_ignores_lifecycle_state_key():
    for extra in ({}, {"lifecycle_state": "有效"}, {"lifecycle_state": None}):
        out = build_retrieval_trace([], _facts(**extra), None)
        assert out == {"facts": [GOLDEN_OFF_FACT], "triples": [], "prompt_lines": None}
        out2 = build_retrieval_trace([], _facts(**extra), None, include_semantic_marks=False)
        assert out2 == out


@pytest.mark.parametrize("state,expected", [
    ("__absent__", sm.PENDING), (None, sm.PENDING),
    *[(s, s) for s in sm.LIFECYCLE_STATES],
    ("亂值", sm.UNKNOWN), (123, sm.UNKNOWN),
])
def test_flag_on_fact_lifecycle_state(state, expected):
    extra = {} if state == "__absent__" else {"lifecycle_state": state}
    off = build_retrieval_trace([], _facts(**extra), None)
    on = build_retrieval_trace([], _facts(**extra), None, include_semantic_marks=True)
    marks = on["facts"][0]["semantic_marks"]
    assert marks["lifecycle_state"] == expected
    assert list(marks)[-1] == "lifecycle_state"
    assert list(marks)[:-1] == ["fields", "relation_type", "article_no", "subject_name_shape", "object_name_shape"]
    stripped = {k: v for k, v in on["facts"][0].items() if k != "semantic_marks"}
    assert stripped == off["facts"][0]


def test_triple_marks_have_no_lifecycle_state():
    from models.knowledge_graph import SVOTriple

    t = SVOTriple(subject="甲", subject_type="Organization", rel_type="CAUSES", verb="導致",
                  object="乙", object_type="概念", source_doc_id=uuid4(), source_article_no="第5條")
    on = build_retrieval_trace([t], [], None, include_semantic_marks=True)
    assert "lifecycle_state" not in on["triples"][0]["semantic_marks"]


# ---- T3 / 5-3：vector_search_facts（假 driver）--------------------------------

def _row(eid, text, score, subject="S", obj="O", **extra):
    return {"fact_id": eid, "fact_text": text, "verb": "V", "confidence": 3, "subject": subject,
            "object": obj, "rel_type": "R", "source_doc_id": "d", "source_svo_chunk_index": 1,
            "score": score, **extra}


class ProjectingDriver:
    """依語句分流回傳；模擬 Neo4j 對 `AS lifecycle_state` 欄位的投影（缺鍵＝null）。"""

    def __init__(self, dense, fulltext=()):
        self.dense, self.fulltext, self.queries = list(dense), list(fulltext), []

    def _project(self, statement, rows):
        out = []
        for r in rows:
            r = dict(r)
            if "AS lifecycle_state" in statement:
                r.setdefault("lifecycle_state", None)
            else:
                r.pop("lifecycle_state", None)
            out.append(r)
        return out

    async def execute_query(self, statement, **params):
        self.queries.append(statement)
        if "db.index.vector.queryNodes" in statement:
            return SimpleNamespace(records=self._project(statement, self.dense))
        if "db.index.fulltext.queryNodes" in statement:
            return SimpleNamespace(records=self._project(statement, self.fulltext))
        return SimpleNamespace(records=[])


@pytest.mark.asyncio
async def test_dense_return_has_lifecycle_state_and_uses_properties_map():
    driver = ProjectingDriver([_row("a", "事實A", 0.9), _row("b", "事實B", 0.8, subject="S2", lifecycle_state="有效")])
    results = await svc.vector_search_facts(driver, uuid4(), [0.1, 0.2], top_k=5)
    knn = [q for q in driver.queries if "db.index.vector.queryNodes" in q]
    assert len(knn) == 1
    assert "properties(node)['lifecycle_state'] AS lifecycle_state" in knn[0]
    assert "node.lifecycle_state" not in knn[0]
    assert [r["fact_text"] for r in results] == ["事實A", "事實B"]
    assert [r["lifecycle_state"] for r in results] == [None, "有效"]
    assert all("fact_id" not in r for r in results)
    assert list(results[0])[-1] == "lifecycle_state"


@pytest.mark.asyncio
async def test_hybrid_fulltext_return_has_lifecycle_state():
    dense = [_row("n1", "雜訊1", 0.85), _row("target", "目標事實", 0.80, subject="T", obj="U")]
    ft = [_row("target", "目標事實", 5.0, subject="T", obj="U")]
    driver = ProjectingDriver(dense, ft)
    results = await svc.vector_search_facts(driver, uuid4(), [0.1, 0.2], top_k=3, question="問", hybrid=True)
    full = [q for q in driver.queries if "db.index.fulltext.queryNodes" in q]
    assert len(full) == 1
    assert "properties(node)['lifecycle_state'] AS lifecycle_state" in full[0]
    assert "node.lifecycle_state" not in full[0]
    assert results[0]["fact_text"] == "目標事實"
    assert all("lifecycle_state" in r and r["lifecycle_state"] is None for r in results)


@pytest.mark.asyncio
async def test_order_and_dedupe_same_as_without_new_column():
    rows = [_row("a", "同鍵高分", 0.9), _row("b", "同鍵低分", 0.5), _row("c", "另一件", 0.7, subject="X")]
    with_col = await svc.vector_search_facts(ProjectingDriver(rows), uuid4(), [0.1], top_k=5)

    class NoCol(ProjectingDriver):
        async def execute_query(self, statement, **params):
            return await super().execute_query(statement.replace("AS lifecycle_state", "AS _dropped"), **params)

    without_col = await svc.vector_search_facts(NoCol(rows), uuid4(), [0.1], top_k=5)
    strip = lambda rs: [{k: v for k, v in r.items() if k != "lifecycle_state"} for r in rs]  # noqa: E731
    assert strip(with_col) == strip(without_col)
    assert [r["fact_text"] for r in with_col] == ["同鍵高分", "另一件"]


# ---- T5-4 結構守衛 ---------------------------------------------------------

def _prod_py():
    skip = {"tests", "docs", ".claude", ".git", "__pycache__", "node_modules", ".venv", "venv"}
    for p in REPO.rglob("*.py"):
        rel = p.relative_to(REPO)
        if skip & set(rel.parts) or any(x.startswith(".pytest-tmp") for x in rel.parts):
            continue
        yield rel, p.read_text(encoding="utf-8", errors="ignore")


def test_no_writes_of_lifecycle_state_anywhere():
    for rel, src in _prod_py():
        if rel.name.startswith("disposable_"):  # 既有的臨時容器驗證腳本（先前報告），非 production 路徑
            continue
        assert "lifecycle_events_json" not in src, rel
        assert not re.search(r"SET\s+\w+\.lifecycle_state", src, re.I), rel


def _imports(src):
    mods = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            mods.append(base)
            mods += [f"{base}.{a.name}" for a in n.names]
    return mods


def test_relation_lifecycle_still_unwired_in_forbidden_places():
    for rel, src in _prod_py():
        parts = rel.parts
        forbidden = (
            rel.as_posix() == "services/semantic_marks.py" or rel.as_posix() == "services/svo_service.py"
            or parts[:2] == ("services", "context") or parts[0] in ("routers", "core")
        )
        if forbidden:
            assert not any("relation_lifecycle" in m for m in _imports(src)), rel


def test_no_state_filtering_in_retrieval_paths():
    for rel, src in _prod_py():
        p = rel.as_posix()
        if p == "services/svo_service.py" or p.startswith(("services/retrieval/", "routers/")):
            assert "DEFAULT_RETRIEVABLE_STATES" not in src, rel
