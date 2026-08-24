import json
from uuid import uuid4

import pytest

from models.document import ChatRequest
from models.knowledge_graph import SVOTriple
from routers import agent


# ── _merge_fact_lines：BFS 三元組與語意檢索 Fact 合併去重（2026-08-18）──────

def _triple(subject="A", rel_type="CAUSES", object_="B", verb="導致"):
    return SVOTriple(subject=subject, subject_type="概念", rel_type=rel_type,
                      verb=verb, object=object_, object_type="概念")


def test_merge_fact_lines_includes_both_sources_when_distinct():
    triples = [_triple("台積電", "CAUSES", "晶片")]
    fact_results = [{"fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
                      "rel_type": "CREATED_BY", "object": "SpaceX"}]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 2
    assert any("台積電" in line for line in lines)
    assert any("馬斯克 創立 SpaceX" in line for line in lines)


def test_merge_fact_lines_dedupes_same_triple_from_both_sources():
    """同一 (subject, rel_type, object) 從 BFS 與語意檢索都找到時，只保留
    先出現的 BFS 版本，不重複列出。"""
    triples = [_triple("台積電", "CAUSES", "晶片", verb="生產")]
    fact_results = [{"fact_text": "台積電（組織） 製造 晶片（產品）", "subject": "台積電",
                      "rel_type": "CAUSES", "object": "晶片"}]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 1
    assert "生產" in lines[0]  # 保留 BFS 版本的措辭，語意檢索版本被去重掉


def test_merge_fact_lines_keeps_fact_with_missing_key_fields():
    """Fact 節點缺 subject/rel_type/object（2026-08-18 schema 修正前建立、
    尚未跑過 §b 回填的舊資料）時，無法安全去重，一律原樣保留。"""
    triples = [_triple("A", "CAUSES", "B")]
    fact_results = [{"fact_text": "舊資料事實", "subject": None, "rel_type": None, "object": None}]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 2
    assert any("舊資料事實" in line for line in lines)


def test_merge_fact_lines_empty_when_no_sources():
    assert agent._merge_fact_lines([], []) == []


# ── _build_prompt：合併後的事實清單接進 prompt ─────────────────────────────

def test_build_prompt_includes_semantic_fact_when_no_bfs_triples():
    """BFS 完全沒找到種子（字面比對失效），但語意檢索找到相關事實時，仍應
    進入「有事實」的 prompt 分支，而非誤判為完全無資料。"""
    fact_results = [{"fact_text": "資遣 需 預告", "subject": "資遣", "rel_type": "REQUIRES", "object": "預告"}]

    prompt = agent._build_prompt("資遣要注意什麼？", [], fact_results, None)

    assert "資遣 需 預告" in prompt
    assert "請優先根據上述事實回答問題" in prompt


def test_build_prompt_falls_back_to_general_knowledge_when_nothing_found():
    prompt = agent._build_prompt("隨便問點什麼", [], [], None)

    assert "沒有檢索到與問題直接相關的事實" in prompt


# ── chat()：驗證語意 Fact 檢索確實接線（2026-08-18）─────────────────────────

class _FakeEmbeddingProvider:
    def __init__(self, vector):
        self._vector = vector
        self.encoded_texts: list[str] = []

    async def encode(self, text: str):
        self.encoded_texts.append(text)
        return self._vector

    async def encode_batch(self, texts: list[str]):
        return [self._vector for _ in texts]


class _FakeStreamLLM:
    def __init__(self):
        self.prompt: str | None = None

    async def stream(self, prompt: str):
        self.prompt = prompt
        yield "ok"


async def _drain(response):
    return [chunk async for chunk in response.body_iterator]


@pytest.mark.asyncio
async def test_chat_wires_vector_search_facts_with_question_embedding_and_top_k(monkeypatch):
    kg_id = uuid4()
    vector_search_calls = []

    async def fake_find_seeds(driver, kg_id_arg, question):
        return []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        vector_search_calls.append((kg_id_arg, vector, top_k))
        return [{"fact_text": "台積電 生產 晶片", "subject": "台積電", "rel_type": "CAUSES", "object": "晶片"}]

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None  # 本測試聚焦 Fact 檢索接線，不驗證關係連結（見專屬測試）

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="台積電是做什麼的？", kg_id=kg_id, top_k=7)
    response = await agent.chat(payload)
    await _drain(response)

    assert embedding.encoded_texts == ["台積電是做什麼的？"]
    assert vector_search_calls == [(kg_id, [0.1, 0.2, 0.3], 7)]
    assert "台積電 生產 晶片" in llm.prompt


@pytest.mark.asyncio
async def test_chat_skips_semantic_search_when_use_svo_is_false(monkeypatch):
    kg_id = uuid4()
    vector_search_calls = []
    embed_calls = []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        vector_search_calls.append((kg_id_arg, vector, top_k))
        return []

    def fake_get_embedding_provider():
        embed_calls.append(True)
        return _FakeEmbeddingProvider([0.0])

    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", fake_get_embedding_provider)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="任意問題", kg_id=kg_id, use_svo=False)
    response = await agent.chat(payload)
    await _drain(response)

    assert vector_search_calls == []
    assert embed_calls == []  # use_svo=False 時完全不呼叫 embedding provider
    assert "沒有檢索到與問題直接相關的事實" in llm.prompt


@pytest.mark.asyncio
async def test_chat_yields_error_event_when_kg_id_missing():
    payload = ChatRequest(question="沒有指定 KG", kg_id=None)

    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(chunks) == 1
    assert "event: error" in chunks[0]


# ── _filter_triples_by_relation_type：§ 3.2 §c QFILTER（2026-08-18）─────────

def test_filter_triples_by_relation_type_keeps_only_matching_type():
    triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    filtered = agent._filter_triples_by_relation_type(triples, "CAUSES")

    assert len(filtered) == 1
    assert filtered[0].subject == "A"


def test_filter_triples_by_relation_type_none_passes_through_unfiltered():
    """QNOMATCH（None）時原樣回傳，不篩選——優雅降級。"""
    triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    filtered = agent._filter_triples_by_relation_type(triples, None)

    assert filtered == triples


def test_filter_triples_by_relation_type_empty_input():
    assert agent._filter_triples_by_relation_type([], "CAUSES") == []


# ── chat()：驗證查詢時關係連結（QSIM/QFILTER）確實接線（2026-08-18）─────────

@pytest.mark.asyncio
async def test_chat_filters_bfs_triples_by_resolved_relation_type(monkeypatch):
    kg_id = uuid4()
    resolve_calls = []
    all_triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    async def fake_find_seeds(driver, kg_id_arg, question):
        return ["A", "C"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return all_triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        resolve_calls.append((question, embedding_provider, llm_provider))
        return "CAUSES"

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="是什麼導致 B 的？", kg_id=kg_id)
    response = await agent.chat(payload)
    await _drain(response)

    assert len(resolve_calls) == 1
    assert resolve_calls[0][0] == "是什麼導致 B 的？"
    assert resolve_calls[0][2] is llm  # llm_provider 有正確傳入
    assert "A（概念）導致B（概念）" in llm.prompt
    assert "C（概念）導致D（概念）" not in llm.prompt  # PART_OF 三元組已被篩掉


@pytest.mark.asyncio
async def test_chat_keeps_all_triples_when_relation_type_unresolved(monkeypatch):
    """QNOMATCH：解析不到型別時，兩個來源的三元組都應該保留。"""
    kg_id = uuid4()
    all_triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    async def fake_find_seeds(driver, kg_id_arg, question):
        return ["A", "C"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return all_triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="隨便問點什麼", kg_id=kg_id)
    response = await agent.chat(payload)
    await _drain(response)

    assert "A（概念）導致B（概念）" in llm.prompt
    assert "C（概念）導致D（概念）" in llm.prompt


# ── _serialize_sources / sources SSE 事件：終端機 CLI 顯示來源用（2026-08-18）──

def test_serialize_sources_includes_triples_facts_and_resolved_rel_type():
    triples = [_triple("A", "CAUSES", "B")]
    fact_results = [{"fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
                      "rel_type": "CREATED_BY", "object": "SpaceX", "score": 0.9}]

    serialized = agent._serialize_sources(triples, fact_results, "CAUSES")

    assert serialized["resolved_rel_type"] == "CAUSES"
    assert serialized["triples"] == [{
        "subject": "A", "subject_type": "概念", "verb": "導致", "object": "B",
        "object_type": "概念", "rel_type": "CAUSES", "source": None,
        "source_svo_chunk_file": None,
    }]
    assert serialized["facts"] == [{
        "fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
        "object": "SpaceX", "rel_type": "CREATED_BY", "score": 0.9,
    }]


def test_serialize_sources_empty_when_nothing_retrieved():
    assert agent._serialize_sources([], [], None) == {
        "resolved_rel_type": None, "triples": [], "facts": [],
    }


@pytest.mark.asyncio
async def test_chat_yields_sources_event_after_answer_stream(monkeypatch):
    kg_id = uuid4()
    triples = [_triple("A", "CAUSES", "B")]

    async def fake_find_seeds(driver, kg_id_arg, question):
        return ["A"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return [{"fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
                  "rel_type": "CREATED_BY", "object": "SpaceX"}]

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return "CAUSES"

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="是什麼導致 B 的？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert chunks[-1].startswith("event: sources\n")
    sources_data = json.loads(chunks[-1].split("\n", 1)[1][len("data: "):])
    assert sources_data["resolved_rel_type"] == "CAUSES"
    assert sources_data["triples"][0]["subject"] == "A"
    assert sources_data["facts"][0]["fact_text"] == "馬斯克 創立 SpaceX"


@pytest.mark.asyncio
async def test_chat_yields_empty_sources_event_when_kg_id_missing():
    """kg_id 缺失時提早 return error 事件，不應該再多送一個 sources 事件。"""
    payload = ChatRequest(question="沒有指定 KG", kg_id=None)

    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(chunks) == 1
    assert "event: sources" not in chunks[0]
