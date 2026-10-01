"""報告221 N1／N2：伺服器端旗標 `TRACE_SEMANTIC_MARKS` 在 `chat()` 路由層的行為證明。

證明範圍（路由整合層，假 provider／假 Neo4j，無 LLM／DB）：
- 旗標關閉（預設）：`retrieval_trace` 不含 `semantic_marks`，靜態型別表**不載入**；
- 旗標開啟：trace 每筆多 `semantic_marks`；除此之外**整串 SSE（回答、sources 的 triples／facts 清單與順序、
  其他事件）與送進 LLM 的 prompt 逐字相同**（僅 `retrieval_latency_ms` 為計時值，先正規化）。
"""

import json
from uuid import uuid4

import pytest

from core.config import Settings
from models.document import ChatRequest
from routers import agent
from services.context import trace_marks
from tests.routers.test_agent import (
    _FakeEmbeddingProvider,
    _FakeStreamLLM,
    _drain,
    _empty_seed_doc_ids,
    _triple,
)


async def _run_chat(monkeypatch, *, flag: bool, scheme: str = "A", with_trace: bool = True):
    kg_id = uuid4()
    triples = [_triple("A", "CAUSES", "B")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["A"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return [
            {"fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克", "rel_type": "CREATED_BY",
             "object": "SpaceX", "verb": "創立", "source_doc_id": None},
            {"fact_text": "丙 規定", "subject": "丙", "rel_type": "RELATED_TO", "object": "", "verb": "規定"},
        ]

    async def fake_resolve(question, embedding_provider, *, llm_provider, cfg=None):
        return "CAUSES"

    llm = _FakeStreamLLM()
    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "_relevant_doc_ids_from_seeds", _empty_seed_doc_ids)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: _FakeEmbeddingProvider([0.1, 0.2, 0.3]))
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)
    monkeypatch.setattr(agent.settings, "trace_semantic_marks", flag)
    monkeypatch.setattr(agent.settings, "trace_semantic_marks_concept_scheme", scheme)

    payload = ChatRequest(question="是什麼導致 B 的？", kg_id=kg_id, include_retrieval_trace=with_trace)
    chunks = await _drain(await agent.chat(payload))
    return chunks, llm


def _sources(chunks: list[str]) -> dict:
    chunk = next(c for c in chunks if c.startswith("event: sources\n"))
    return json.loads(chunk.split("\n", 1)[1][len("data: "):])


def _normalize(chunks: list[str]) -> list:
    """sources 事件解析後把計時值歸零並剝掉 `semantic_marks` 鍵；其餘 chunk 原樣保留。"""
    out = []
    for c in chunks:
        if c.startswith("event: sources\n"):
            s = _sources([c])
            if s.get("retrieval_telemetry"):
                s["retrieval_telemetry"]["retrieval_latency_ms"] = 0
            for e in ((s.get("retrieval_trace") or {}).get("facts", []) + (s.get("retrieval_trace") or {}).get("triples", [])):
                e.pop("semantic_marks", None)
            out.append(s)
        else:
            out.append(c)
    return out


def test_settings_defaults_off_and_scheme_a():
    s = Settings(_env_file=None)
    assert s.trace_semantic_marks is False
    assert s.trace_semantic_marks_concept_scheme == "A"


@pytest.mark.asyncio
async def test_flag_off_default_trace_has_no_marks_and_never_loads_type_tables(monkeypatch):
    def boom():
        raise AssertionError("旗標關閉時不得載入型別表")

    monkeypatch.setattr(trace_marks, "load_type_lookups", boom)
    chunks, _ = await _run_chat(monkeypatch, flag=False)
    trace = _sources(chunks)["retrieval_trace"]
    assert trace["facts"] and trace["triples"]
    for e in trace["facts"] + trace["triples"]:
        assert "semantic_marks" not in e


@pytest.mark.asyncio
async def test_flag_on_adds_marks_to_every_entry(monkeypatch):
    chunks, _ = await _run_chat(monkeypatch, flag=True)
    trace = _sources(chunks)["retrieval_trace"]
    entries = trace["facts"] + trace["triples"]
    assert entries and all("semantic_marks" in e for e in entries)
    fact_marks = trace["facts"][1]["semantic_marks"]  # 空受詞但有 verb ＝ 尚未處理
    assert fact_marks["fields"] == "尚未處理"
    assert "subject_type" not in fact_marks  # Fact 端點型別需對 Entity，trace 內不查 DB
    tm = trace["triples"][0]["semantic_marks"]
    assert tm["subject_type"] == "未知"  # 概念＋方案A＝未知


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme,expected", [("A", "未知"), ("B", "已解決"), ("strict", "無法由現有資料判定")])
async def test_flag_on_concept_scheme_is_applied(monkeypatch, scheme, expected):
    chunks, _ = await _run_chat(monkeypatch, flag=True, scheme=scheme)
    assert _sources(chunks)["retrieval_trace"]["triples"][0]["semantic_marks"]["subject_type"] == expected


@pytest.mark.asyncio
async def test_flag_on_does_not_change_answer_sources_order_or_prompt(monkeypatch):
    off_chunks, off_llm = await _run_chat(monkeypatch, flag=False)
    on_chunks, on_llm = await _run_chat(monkeypatch, flag=True)
    assert _normalize(on_chunks) == _normalize(off_chunks)  # 回答、事件順序、triples／facts 清單與順序皆相同
    assert on_llm.prompts == off_llm.prompts                # 送進 LLM 的 prompt（含事實行）逐字相同
    off_s, on_s = _sources(off_chunks), _sources(on_chunks)
    assert on_s["triples"] == off_s["triples"] and on_s["facts"] == off_s["facts"]


@pytest.mark.asyncio
async def test_flag_without_trace_request_has_no_effect(monkeypatch):
    def boom():
        raise AssertionError("未要求 trace 時不得載入型別表")

    monkeypatch.setattr(trace_marks, "load_type_lookups", boom)
    chunks, _ = await _run_chat(monkeypatch, flag=True, with_trace=False)
    assert _sources(chunks)["retrieval_trace"] is None


@pytest.mark.asyncio
async def test_flag_on_invalid_scheme_raises_clearly(monkeypatch):
    with pytest.raises(ValueError):
        await _run_chat(monkeypatch, flag=True, scheme="bogus")
