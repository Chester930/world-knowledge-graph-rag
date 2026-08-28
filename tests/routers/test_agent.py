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


# ── _merge_fact_lines：殘缺三元組過濾（2026-08-27，64筆規模抽查發現）───────

def test_merge_fact_lines_skips_triple_with_empty_object():
    """BFS 三元組 object 為空字串（列舉式抽取失敗殘留）時整筆跳過，不送進 prompt。"""
    triples = [_triple("失業給付", "RELATED_TO", "")]

    lines = agent._merge_fact_lines(triples, [])

    assert lines == []


def test_merge_fact_lines_skips_triple_with_empty_subject():
    triples = [_triple("", "RELATED_TO", "B")]

    lines = agent._merge_fact_lines(triples, [])

    assert lines == []


def test_merge_fact_lines_skips_fact_with_empty_object_string():
    """fact_results 的 object 是明確的空字串（非 None）時跳過——區分於
    「舊資料尚未回填、缺席為 None」的既有保留邏輯（見上一則測試）。"""
    fact_results = [{"fact_text": "失業給付（概念）  （概念）", "subject": "失業給付",
                      "rel_type": "RELATED_TO", "object": ""}]

    lines = agent._merge_fact_lines([], fact_results)

    assert lines == []


def test_merge_fact_lines_keeps_valid_triples_and_facts_when_mixed_with_blank_ones():
    triples = [_triple("A", "CAUSES", "B"), _triple("殘缺", "RELATED_TO", "")]
    fact_results = [
        {"fact_text": "有效事實", "subject": "C", "rel_type": "CAUSES", "object": "D"},
        {"fact_text": "殘缺事實", "subject": "", "rel_type": "RELATED_TO", "object": "E"},
    ]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 2
    assert any("A" in line for line in lines)
    assert any("有效事實" in line for line in lines)


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
    def __init__(
        self,
        grounding_payload: str = '{"claims":[]}',
        *,
        answers: list[str] | None = None,
        grounding_payloads: list[str] | None = None,
    ):
        self.prompt: str | None = None
        self.prompts: list[str] = []  # 2026-08-28：方案 B 可能呼叫 stream() 兩次（草稿＋修正）
        self.grounding_payload = grounding_payload
        self.grounding_prompts: list[str] = []
        # 2026-08-28：`answers`／`grounding_payloads` 依序供應每次呼叫的回應，
        # 用完最後一個之後重複沿用——讓測試能模擬「草稿未接地→限制性重新生成
        # →修正版已接地」這種依 prompt 內容遞增變化的情境，不需要真的解析
        # prompt 內容來決定回應。
        self._answers = list(answers) if answers is not None else None
        self._grounding_payloads = list(grounding_payloads) if grounding_payloads is not None else None

    async def stream(self, prompt: str):
        self.prompt = prompt
        self.prompts.append(prompt)
        if self._answers:
            text = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        else:
            text = "ok"
        yield text

    async def generate_json(self, prompt: str) -> str:
        # 2026-08-24：verify_fact_grounding() 串流結束後呼叫；預設回傳空
        # claims，既有測試（聚焦串流/檢索接線本身）不需要另外準備核對回應。
        self.grounding_prompts.append(prompt)
        if self._grounding_payloads:
            return self._grounding_payloads.pop(0) if len(self._grounding_payloads) > 1 else self._grounding_payloads[0]
        return self.grounding_payload


async def _drain(response):
    return [chunk async for chunk in response.body_iterator]


# ── _find_seed_entities：字面比對 + 語意 fallback（2026-08-25，見 docs/報告/17）──

class _FakeEntityDriver:
    def __init__(self, names):
        self._names = names

    async def execute_query(self, query, **params):
        class _Result:
            def __init__(self, records):
                self.records = records

        return _Result([{"name": n} for n in self._names])


@pytest.mark.asyncio
async def test_find_seed_entities_prefers_literal_match_over_vector_fallback(monkeypatch):
    """字面比對命中時，不應呼叫語意 fallback（優先採用更精確的字面匹配，
    見函式 docstring）。"""
    driver = _FakeEntityDriver(["勞工", "雇主"])
    vector_calls = []

    async def fake_vector_search(driver_arg, kg_id_arg, vector, top_k):
        vector_calls.append(True)
        return []

    monkeypatch.setattr(agent, "vector_search_entities", fake_vector_search)
    embedding = _FakeEmbeddingProvider([0.1])

    seeds = await agent._find_seed_entities(
        driver, uuid4(), "勞工可以請幾天婚假？", embedding_provider=embedding,
    )

    assert seeds == ["勞工"]
    assert vector_calls == []


@pytest.mark.asyncio
async def test_find_seed_entities_falls_back_to_vector_search_when_no_literal_match(monkeypatch):
    """2026-08-25 新增：字面比對找不到任何種子、且提供 `embedding_provider`
    時，改用 `vector_search_entities()` 的語意相似度結果。"""
    driver = _FakeEntityDriver(["請婚假、喪假、公傷病假及公假"])  # 不含「婚假」字面子字串比對不到

    async def fake_vector_search(driver_arg, kg_id_arg, vector, top_k):
        assert vector == [0.1, 0.2]
        assert top_k == agent._SEED_ENTITY_LIMIT
        return ["婚假"]

    monkeypatch.setattr(agent, "vector_search_entities", fake_vector_search)
    embedding = _FakeEmbeddingProvider([0.1, 0.2])

    seeds = await agent._find_seed_entities(
        driver, uuid4(), "婚假可以請幾天？",
        embedding_provider=embedding, question_vector=[0.1, 0.2],
    )

    assert seeds == ["婚假"]


@pytest.mark.asyncio
async def test_find_seed_entities_without_embedding_provider_stays_empty_on_no_match():
    """`embedding_provider=None`（既有呼叫端未升級）時行為與新增語意
    fallback 之前完全一致——不嘗試向量比對，直接回傳空清單。"""
    driver = _FakeEntityDriver(["請婚假、喪假、公傷病假及公假"])

    seeds = await agent._find_seed_entities(driver, uuid4(), "婚假可以請幾天？")

    assert seeds == []


@pytest.mark.asyncio
async def test_chat_wires_vector_search_facts_with_question_embedding_and_top_k(monkeypatch):
    kg_id = uuid4()
    vector_search_calls = []

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
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


# ── _relevant_doc_ids_from_facts／_filter_triples_by_source_doc_ids：
# 借用語意 Fact 檢索結果當 BFS 前置篩選範圍（2026-08-27）─────────────────────

def test_relevant_doc_ids_from_facts_collects_unique_ids():
    doc_a, doc_b = uuid4(), uuid4()
    fact_results = [
        {"fact_text": "F1", "source_doc_id": str(doc_a)},
        {"fact_text": "F2", "source_doc_id": str(doc_a)},
        {"fact_text": "F3", "source_doc_id": str(doc_b)},
    ]

    ids = agent._relevant_doc_ids_from_facts(fact_results)

    assert ids == {doc_a, doc_b}


def test_relevant_doc_ids_from_facts_ignores_missing_or_invalid():
    doc_a = uuid4()
    fact_results = [
        {"fact_text": "F1", "source_doc_id": str(doc_a)},
        {"fact_text": "F2", "source_doc_id": None},
        {"fact_text": "F3"},
        {"fact_text": "F4", "source_doc_id": "not-a-uuid"},
    ]

    ids = agent._relevant_doc_ids_from_facts(fact_results)

    assert ids == {doc_a}


def test_relevant_doc_ids_from_facts_empty_when_no_facts():
    assert agent._relevant_doc_ids_from_facts([]) == set()


def test_filter_triples_by_source_doc_ids_keeps_matching_and_unknown():
    """排除篩選：只排除明確知道來源、且不在允許範圍內的三元組；
    source_doc_id 為 None（無法判定）一律保留。"""
    doc_a, doc_b = uuid4(), uuid4()
    triple_in_range = _triple("A", "CAUSES", "B")
    triple_in_range.source_doc_id = doc_a
    triple_out_of_range = _triple("C", "CAUSES", "D")
    triple_out_of_range.source_doc_id = doc_b
    triple_unknown = _triple("E", "CAUSES", "F")
    triple_unknown.source_doc_id = None

    filtered = agent._filter_triples_by_source_doc_ids(
        [triple_in_range, triple_out_of_range, triple_unknown], {doc_a}
    )

    assert filtered == [triple_in_range, triple_unknown]


def test_filter_triples_by_source_doc_ids_no_filter_when_allowed_set_empty():
    """語意檢索沒有找到任何範圍訊號（allowed_doc_ids 為空）時原樣回傳，
    不強加篩選——優雅降級，不因為沒有篩選依據就讓查詢端拿不到結果。"""
    triples = [_triple("A", "CAUSES", "B"), _triple("C", "CAUSES", "D")]

    filtered = agent._filter_triples_by_source_doc_ids(triples, set())

    assert filtered == triples


# ── chat()：驗證查詢時關係連結（QSIM/QFILTER）確實接線（2026-08-18）─────────

@pytest.mark.asyncio
async def test_chat_filters_bfs_triples_by_resolved_relation_type(monkeypatch):
    kg_id = uuid4()
    resolve_calls = []
    all_triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
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

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
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
        "source_svo_chunk_file": None, "document": None,
    }]
    assert serialized["facts"] == [{
        "fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
        "object": "SpaceX", "rel_type": "CREATED_BY", "score": 0.9,
        "document": None,
    }]


def test_serialize_sources_empty_when_nothing_retrieved():
    assert agent._serialize_sources([], [], None) == {
        "resolved_rel_type": None, "triples": [], "facts": [],
    }


# ── _serialize_sources 引用豐富化：附加 Document 中繼資料（2026-08-25）───────

def test_serialize_sources_attaches_document_metadata_when_available():
    """`document_map` 有對應 `source_doc_id` 時，triples／facts 都附加
    `effective_date` 等法規層級中繼資料，供回答來源標註現行狀態。"""
    from models.law_document import LawDocument

    doc_id = uuid4()
    triple = SVOTriple(subject="A", subject_type="概念", rel_type="CAUSES",
                        verb="導致", object="B", object_type="概念", source_doc_id=doc_id)
    fact_results = [{"fact_text": "F", "subject": "A", "object": "B",
                      "rel_type": "CAUSES", "score": 0.9, "source_doc_id": str(doc_id)}]
    doc = LawDocument(kg_id=uuid4(), source_doc_id=doc_id, source="s", title="勞工請假規則",
                       record_type="law", content_hash="h", update_date="20251209",
                       effective_date=None, effective_note="施行日另定")
    document_map = {str(doc_id): doc}

    serialized = agent._serialize_sources([triple], fact_results, "CAUSES", document_map)

    expected_document = {
        "title": "勞工請假規則", "update_date": "20251209",
        "effective_date": None, "effective_note": "施行日另定",
    }
    assert serialized["triples"][0]["document"] == expected_document
    assert serialized["facts"][0]["document"] == expected_document


def test_serialize_sources_document_none_when_source_doc_id_missing_from_map():
    """`source_doc_id` 存在但 `document_map` 查無對應（一般文件，或尚未
    跑過 Document/LawArticle 匯入的舊 KG）時優雅退化為 `None`，不拋例外。"""
    triple = SVOTriple(subject="A", subject_type="概念", rel_type="CAUSES",
                        verb="導致", object="B", object_type="概念", source_doc_id=uuid4())

    serialized = agent._serialize_sources([triple], [], "CAUSES", document_map={})

    assert serialized["triples"][0]["document"] is None


@pytest.mark.asyncio
async def test_fetch_document_map_dedupes_and_skips_lookup_when_no_doc_ids(monkeypatch):
    """triples／facts 都沒有 `source_doc_id` 時完全不呼叫 repository（不需要
    真的能連線的 driver）；有重複的 `source_doc_id` 時只查一次。"""

    class _ExplodingRepo:
        def __init__(self, driver):
            raise AssertionError("doc_ids 為空時不應建立 repository")

    monkeypatch.setattr(agent, "LawDocumentRepository", _ExplodingRepo)

    result = await agent._fetch_document_map(
        "fake-driver", uuid4(), [_triple("A", "CAUSES", "B")], [{"fact_text": "F"}]
    )

    assert result == {}


@pytest.mark.asyncio
async def test_fetch_document_map_returns_map_keyed_by_source_doc_id_string(monkeypatch):
    from models.law_document import LawDocument

    doc_id = uuid4()
    doc = LawDocument(kg_id=uuid4(), source_doc_id=doc_id, source="s", title="T",
                       record_type="law", content_hash="h")
    calls: list = []

    class _FakeRepo:
        def __init__(self, driver):
            pass

        async def get_document(self, kg_id, source_doc_id):
            calls.append(source_doc_id)
            return doc if source_doc_id == doc_id else None

    monkeypatch.setattr(agent, "LawDocumentRepository", _FakeRepo)
    triple = SVOTriple(subject="A", subject_type="概念", rel_type="CAUSES",
                        verb="導致", object="B", object_type="概念", source_doc_id=doc_id)

    result = await agent._fetch_document_map("fake-driver", uuid4(), [triple], [])

    assert calls == [doc_id]
    assert result == {str(doc_id): doc}


@pytest.mark.asyncio
async def test_chat_yields_sources_event_after_answer_stream(monkeypatch):
    kg_id = uuid4()
    triples = [_triple("A", "CAUSES", "B")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
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

    # 2026-08-24：event: grounding 在 sources 之後才送出（見該測試），
    # sources 因此不再是最後一個 chunk，改用 event 類型定位。
    sources_chunk = next(c for c in chunks if c.startswith("event: sources\n"))
    sources_data = json.loads(sources_chunk.split("\n", 1)[1][len("data: "):])
    assert sources_data["resolved_rel_type"] == "CAUSES"
    assert sources_data["triples"][0]["subject"] == "A"
    assert sources_data["facts"][0]["fact_text"] == "馬斯克 創立 SpaceX"


@pytest.mark.asyncio
async def test_chat_yields_grounding_event_after_sources(monkeypatch):
    """2026-08-24：串流結束後應額外送出 event: grounding（見 § 3.6 設計提案
    ／`docs/報告/16_事實接地性核對機制設計報告.md`），且順序在 sources 之後。"""
    kg_id = uuid4()

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return [{"fact_text": "公務員每日辦公時數為八小時。", "subject": "公務員",
                  "rel_type": "HAS_PROPERTY", "object": "八小時"}]

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(grounding_payload=json.dumps({
        "claims": [{"statement": "ok", "supported": False, "reason": "查無此數字"}]
    }))

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="考試院公務員每日辦公時數是幾小時？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    # 2026-08-28：方案 B 升級後，grounding 判定未接地會觸發限制性重新生成，
    # event: grounding 之後還會多送一個 event: status（phase=done），不再是
    # 最後一個 chunk，改用 event 類型定位（比照 sources 定位方式）。
    grounding_chunk = next(c for c in chunks if c.startswith("event: grounding\n"))
    grounding_data = json.loads(grounding_chunk.split("\n", 1)[1][len("data: "):])
    assert grounding_data == [{"statement": "ok", "supported": False, "reason": "查無此數字"}]
    # 待核對文字（串流累積的完整回答）與 fact_text 清單皆確實送進了核對呼叫
    assert "公務員每日辦公時數為八小時。" in llm.grounding_prompts[0]


@pytest.mark.asyncio
async def test_chat_grounding_check_includes_bfs_triples_not_just_vector_facts(monkeypatch):
    """2026-08-24 真實測試發現的迴歸案例：核對範圍必須與 `_build_prompt()`
    實際餵給生成模型的 context 一致（`_merge_fact_lines()`），只用
    `fact_results` 會把 BFS 三元組來源的正確陳述誤判為未接地（假陽性）。"""
    kg_id = uuid4()
    triples = [_triple("公務員", "HAS_PROPERTY", "四十小時", verb="每週辦公總時數為")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["公務員"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []  # 這筆事實只由 BFS 找到，語意檢索沒有對應結果

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

    payload = ChatRequest(question="公務員每週辦公總時數多少？", kg_id=kg_id)
    response = await agent.chat(payload)
    await _drain(response)

    assert len(llm.grounding_prompts) == 1
    assert "公務員" in llm.grounding_prompts[0] and "四十小時" in llm.grounding_prompts[0]


@pytest.mark.asyncio
async def test_chat_yields_empty_grounding_event_when_no_facts_retrieved(monkeypatch):
    """未檢索到任何 Fact 時，`verify_fact_grounding()` 不呼叫 LLM 但仍應送出
    `event: grounding`（見該函式 docstring：明確標記未接地，不可靜默省略整個
    事件）。"""
    kg_id = uuid4()

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return []

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
    chunks = await _drain(response)

    grounding_chunk = next(c for c in chunks if c.startswith("event: grounding\n"))
    grounding_data = json.loads(grounding_chunk.split("\n", 1)[1][len("data: "):])
    assert len(grounding_data) == 1
    assert grounding_data[0]["supported"] is False
    assert llm.grounding_prompts == []  # 沒有 Fact 可供比對，不呼叫 LLM（兩次核對皆短路）


# ── 方案 B：限制性重新生成（2026-08-28，見 docs/報告/16 § 3、6）──


def _chat_common_monkeypatch(monkeypatch, llm, embedding, *, triples=None, facts=None):
    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["A"] if triples else []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops):
        return triples or []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return facts or []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)


@pytest.mark.asyncio
async def test_chat_no_regeneration_when_fully_grounded(monkeypatch):
    """全部陳述句皆接地時，不應該多花一次 LLM 呼叫重新生成——這是方案 B
    刻意設計的成本控制（見 chat() docstring：只有真的抓到未接地內容才多付
    一次生成的延遲）。"""
    kg_id = uuid4()
    facts = [{"fact_text": "婚假為八日", "subject": "婚假", "rel_type": "HAS_PROPERTY", "object": "八日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["婚假為八日。"],
        grounding_payloads=[json.dumps({"claims": [{"statement": "婚假為八日。", "supported": True, "reason": ""}]})],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="婚假幾天？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(llm.prompts) == 1  # 沒有觸發第二次（限制性重新生成）呼叫
    data_chunk = next(c for c in chunks if c.startswith("data: "))
    assert json.loads(data_chunk[len("data: "):])["token"] == "婚假為八日。"
    done_chunk = next(
        c for c in chunks if c.startswith("event: status\n") and '"phase": "done"' in c
    )
    assert json.loads(done_chunk.split("\n", 1)[1][len("data: "):])["regenerated"] is False


@pytest.mark.asyncio
async def test_chat_regenerates_with_constrained_prompt_when_ungrounded(monkeypatch):
    """草稿有未接地陳述時，應該用 `_build_constrained_prompt()` 重新生成一次，
    使用者最終收到的 `data:` 事件是修正版而非草稿（對應使用者要求「寧願說
    不知道，也禁止亂回答」）。"""
    kg_id = uuid4()
    facts = [{"fact_text": "婚假為八日", "subject": "婚假", "rel_type": "HAS_PROPERTY", "object": "八日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["婚假三日，我自己推測的。", "資料未明確記載，無法確認婚假天數。"],
        grounding_payloads=[
            json.dumps({"claims": [{"statement": "婚假三日", "supported": False, "reason": "查無此數字"}]}),
            json.dumps({"claims": [{"statement": "資料未明確記載，無法確認婚假天數。", "supported": True, "reason": ""}]}),
        ],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="婚假幾天？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(llm.prompts) == 2  # 草稿 + 限制性重新生成各一次
    constrained_prompt = llm.prompts[1]
    assert "婚假三日" in constrained_prompt  # 把未接地陳述列出來要求不要重複
    assert "資料未明確記載" in constrained_prompt  # 明確要求答不知道而非臆測

    data_chunk = next(c for c in chunks if c.startswith("data: "))
    assert json.loads(data_chunk[len("data: "):])["token"] == "資料未明確記載，無法確認婚假天數。"
    assert "婚假三日" not in data_chunk  # 使用者最終看到的不是未接地的草稿

    done_chunk = next(
        c for c in chunks if c.startswith("event: status\n") and '"phase": "done"' in c
    )
    assert json.loads(done_chunk.split("\n", 1)[1][len("data: "):])["regenerated"] is True

    grounding_chunk = next(c for c in chunks if c.startswith("event: grounding\n"))
    grounding_data = json.loads(grounding_chunk.split("\n", 1)[1][len("data: "):])
    assert grounding_data[0]["supported"] is True  # 反映修正版，非草稿的核對結果


@pytest.mark.asyncio
async def test_chat_emits_status_events_in_expected_order(monkeypatch):
    kg_id = uuid4()
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()  # 預設空 claims，不觸發重新生成
    _chat_common_monkeypatch(monkeypatch, llm, embedding)

    payload = ChatRequest(question="任意問題", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    status_phases = [
        json.loads(c.split("\n", 1)[1][len("data: "):])["phase"]
        for c in chunks
        if c.startswith("event: status\n")
    ]
    assert status_phases == ["generating", "verifying", "done"]


@pytest.mark.asyncio
async def test_chat_yields_empty_sources_event_when_kg_id_missing():
    """kg_id 缺失時提早 return error 事件，不應該再多送一個 sources 事件。"""
    payload = ChatRequest(question="沒有指定 KG", kg_id=None)

    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(chunks) == 1
    assert "event: sources" not in chunks[0]
