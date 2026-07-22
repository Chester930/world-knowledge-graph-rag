import json
import re
from uuid import uuid4

import pytest

from models.knowledge_graph import SVOTriple
from services import svo_service as svc


class FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload
        self.prompts = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload

    async def stream(self, prompt: str):
        yield self.payload

    async def generate_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload


class FakeEmbedding:
    """合成向量 embedding provider：把每個獨立字串映射到一個正交基底向量，
    可透過 `similar_to` 讓兩個不同字串共享同一個向量方向（模擬高 cosine 相似度）。
    """

    def __init__(self, similar_to: dict[str, str] | None = None):
        self._similar_to = similar_to or {}
        self._index: dict[str, int] = {}

    @property
    def dim(self) -> int:
        return 8

    @property
    def model_name(self) -> str:
        return "fake-embedding"

    def encode(self, text: str) -> list[float]:
        key = self._similar_to.get(text, text)
        if key not in self._index:
            self._index[key] = len(self._index)
        idx = self._index[key] % self.dim
        vec = [0.0] * self.dim
        vec[idx] = 1.0
        return vec

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


class FakeResult:
    def __init__(self, records=None):
        self.records = records or []


class FakeRecord(dict):
    pass


class FakeDriver:
    def __init__(self, records=None):
        self.calls = []
        self.records = records or []

    async def execute_query(self, query: str, **params):
        self.calls.append((query, params))
        return FakeResult(self.records)


class InMemoryEntityDriver:
    """簡化的 Neo4j driver 替身：辨識 merge_entity／merge_triples_to_graph
    實際發出的查詢形狀，用 dict 模擬 Entity／Chunk 節點與 HAS_ENTITY 邊的
    MERGE／rename／聚合狀態，讓實體去重/RECHECK 邏輯可在不連線真實 Neo4j
    的情況下正確驗證，資料模型對應 3.4 §b 文字描述的
    `(Chunk)-[:HAS_ENTITY {surface_form}]->(Entity)` 邊。"""

    def __init__(self):
        self.entities: dict[tuple[str, str], dict] = {}  # (kg_id, name) -> {type}
        self.has_entity_edges: dict[tuple, int] = {}  # (kg_id, chunk_key, entity_name, surface_form) -> count（供除錯用，非邏輯必需）
        # (kg_id, rel_type, subject, object) -> {citations_json, confidence}：事實層級去重後，
        # 同一組 (subject, rel_type, object) 只有一筆，不再依 chunk/句子區分。
        self.relationships: dict[tuple, dict] = {}
        self.queries: list[str] = []

    async def execute_query(self, query: str, **params):
        self.queries.append(query)
        stripped = query.strip()

        if stripped.startswith("MATCH (e:Entity {kg_id: $kg_id, type: $entity_type})"):
            kg_id, entity_type = params["kg_id"], params["entity_type"]
            records = [
                {"name": name} for (kid, name), data in self.entities.items()
                if kid == kg_id and data["type"] == entity_type
            ]
            return FakeResult(records)

        if stripped.startswith("MERGE (e:Entity {kg_id: $kg_id, name: $name}) ON CREATE SET"):
            key = (params["kg_id"], params["name"])
            self.entities.setdefault(key, {"type": params["entity_type"]})
            return FakeResult([])

        if stripped.startswith("MERGE (c:Chunk"):
            kg_id = params["kg_id"]
            entity_key = (kg_id, params["entity_name"])
            self.entities.setdefault(entity_key, {"type": params["entity_type"]})
            chunk_key = (kg_id, params["source_doc_id"], params["chunk_index"])
            edge_key = (kg_id, chunk_key, params["entity_name"], params["surface_form"])
            self.has_entity_edges[edge_key] = self.has_entity_edges.get(edge_key, 0) + 1
            return FakeResult([])

        if stripped.startswith("MATCH (c:Chunk {kg_id: $kg_id})-[r:HAS_ENTITY]->"):
            # 對應真實 Cypher 的 count(DISTINCT c.source_doc_id)：同一份文件
            # 內多個 chunk 各自建立的邊，只算一票，避免單一文件因 chunk 數量
            # 多而在跨文件頻率上灌票（2026-07-21 修訂）。
            kg_id, entity_name = params["kg_id"], params["entity_name"]
            doc_ids_by_alias: dict[str, set] = {}
            for (kid, chunk_key, ename, surface_form) in self.has_entity_edges:
                if kid == kg_id and ename == entity_name:
                    source_doc_id = chunk_key[1]
                    doc_ids_by_alias.setdefault(surface_form, set()).add(source_doc_id)
            records = [{"alias": alias, "freq": len(doc_ids)} for alias, doc_ids in doc_ids_by_alias.items()]
            return FakeResult(records)

        if stripped.startswith("MATCH (e:Entity {kg_id: $kg_id, name: $resolved_name}) SET"):
            kg_id = params["kg_id"]
            old_key = (kg_id, params["resolved_name"])
            existing = self.entities.get(old_key, {"type": None})
            self.entities.pop(old_key, None)
            new_key = (kg_id, params["final_name"])
            self.entities[new_key] = {"type": existing["type"], "aliases": params["aliases"]}
            # 已記錄的 HAS_ENTITY 邊改指向新名稱，模擬節點改名後既有邊仍連著同一節點
            for edge_key in list(self.has_entity_edges):
                kid, chunk_key, ename, surface_form = edge_key
                if kid == kg_id and ename == params["resolved_name"]:
                    count = self.has_entity_edges.pop(edge_key)
                    self.has_entity_edges[(kid, chunk_key, params["final_name"], surface_form)] = count
            return FakeResult([])

        if "MERGE (s)-[r:" in stripped and "RETURN r.citations_json" in stripped:
            key = self._rel_key(stripped, params)
            existing = self.relationships.setdefault(key, {"citations_json": "[]", "confidence": 1})
            return FakeResult([{"citations_json": existing["citations_json"]}])

        if "SET r.citations_json" in stripped:
            key = self._rel_key(stripped, params)
            self.relationships[key] = {
                "citations_json": params["citations_json"],
                "confidence": params["confidence"],
            }
            return FakeResult([])

        return FakeResult([])

    @staticmethod
    def _rel_key(query: str, params: dict) -> tuple:
        rel_type_match = re.search(r"\[r:`([A-Z_]+)`", query)
        rel_type = rel_type_match.group(1) if rel_type_match else None
        return (params["kg_id"], rel_type, params["subject"], params["object"])


@pytest.mark.asyncio
async def test_extract_svo_triples_parses_valid_json_and_filters_invalid_rel_type():
    llm = FakeLLM("""
    {"triples":[
      {"subject":"A","rel_type":"CAUSES","verb":"導致","object":"B","confidence":4},
      {"subject":"X","rel_type":"NOT_ALLOWED","verb":"關係","object":"Y","confidence":3}
    ]}
    """)

    triples = await svc.extract_svo_triples("A 導致 B。", llm)

    assert len(triples) == 1
    assert triples[0].subject == "A"
    assert triples[0].rel_type == "CAUSES"
    assert "合法 rel_type" in llm.prompts[0]


@pytest.mark.asyncio
async def test_extract_svo_triples_without_provider_returns_empty_list():
    assert await svc.extract_svo_triples("A 導致 B。") == []


@pytest.mark.asyncio
async def test_merge_triples_to_graph_accumulates_citation_on_edge():
    """對應 2026-07-22 使用者確認：事實層級去重——關係邊的 MERGE 鍵不再含
    chunk/句子欄位，來源改記錄在邊上累積的 `citations_json`。"""
    driver = FakeDriver()
    kg_id = uuid4()
    doc_id = uuid4()
    triple = SVOTriple(
        subject="A",
        rel_type="CAUSES",
        verb="導致",
        object="B",
        source_doc_id=doc_id,
        source_svo_chunk_index=2,
        source_svo_chunk_file="svo-chunk-002-of-003.md",
        source_sentence_start=5,
        source_sentence_end=7,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [triple])

    set_calls = [(q, p) for q, p in driver.calls if "SET r.citations_json = $citations_json" in q]
    assert len(set_calls) == 1
    _, params = set_calls[0]
    assert params["kg_id"] == str(kg_id)
    assert params["subject"] == "A"
    assert params["object"] == "B"

    citations = json.loads(params["citations_json"])
    assert len(citations) == 1
    assert citations[0]["source_doc_id"] == str(doc_id)
    assert citations[0]["source_svo_chunk_index"] == 2
    assert citations[0]["source_sentence_start"] == 5
    assert citations[0]["source_sentence_end"] == 7
    assert citations[0]["verb"] == "導致"


# ── resolve_entity_name（DEDUP4＋ESCALATE 純邏輯）──────────────────────────

@pytest.mark.asyncio
async def test_resolve_entity_name_returns_original_when_no_candidates():
    assert await svc.resolve_entity_name("台積電", []) == "台積電"


@pytest.mark.asyncio
async def test_resolve_entity_name_merges_via_edit_distance():
    candidates = [{"name": "台積電公司", "alias_counts_json": "{}"}]
    resolved = await svc.resolve_entity_name("台積電", candidates)
    assert resolved == "台積電公司"


@pytest.mark.asyncio
async def test_resolve_entity_name_merges_via_cosine_similarity():
    embedding = FakeEmbedding(similar_to={"I-35": "Interstate Highway 35"})
    candidates = [{"name": "Interstate Highway 35", "alias_counts_json": "{}"}]

    resolved = await svc.resolve_entity_name(
        "I-35", candidates, embedding_provider=embedding
    )

    assert resolved == "Interstate Highway 35"


@pytest.mark.asyncio
async def test_resolve_entity_name_without_embedding_provider_creates_new_entity():
    candidates = [{"name": "Interstate Highway 35", "alias_counts_json": "{}"}]
    resolved = await svc.resolve_entity_name("I-35", candidates)
    assert resolved == "I-35"


@pytest.mark.asyncio
async def test_resolve_entity_name_escalates_gray_zone_to_llm():
    # "Foo Company"／"XYZ Corp" 編輯距離比對 ratio ≈ 0.42（遠低於門檻），
    # 確保不會被編輯距離規則捷徑攔截，真正走到 cosine／LLM 仲裁這一段。
    import math

    def fake_encode(text: str) -> list[float]:
        angle = 0.6 if text == "Foo Company" else 0.0  # cos(0.6) ≈ 0.825，落在灰色地帶
        return [math.cos(angle), math.sin(angle)] + [0.0] * 6

    embedding = FakeEmbedding()
    embedding.encode = fake_encode  # type: ignore[method-assign]
    embedding.encode_batch = lambda texts: [fake_encode(t) for t in texts]  # type: ignore[method-assign]

    candidates = [{"name": "XYZ Corp", "alias_counts_json": "{}"}]
    llm = FakeLLM("是")

    resolved = await svc.resolve_entity_name(
        "Foo Company", candidates, embedding_provider=embedding, llm_provider=llm
    )

    assert resolved == "XYZ Corp"
    assert "Foo Company" in llm.prompts[0] and "XYZ Corp" in llm.prompts[0]


@pytest.mark.asyncio
async def test_resolve_entity_name_gray_zone_without_llm_creates_new_entity():
    import math

    def fake_encode(text: str) -> list[float]:
        angle = 0.6 if text == "Foo Company" else 0.0
        return [math.cos(angle), math.sin(angle)] + [0.0] * 6

    embedding = FakeEmbedding()
    embedding.encode = fake_encode  # type: ignore[method-assign]

    candidates = [{"name": "XYZ Corp", "alias_counts_json": "{}"}]
    resolved = await svc.resolve_entity_name("Foo Company", candidates, embedding_provider=embedding)
    assert resolved == "Foo Company"


# ── merge_entity（含 RECORD3B／RECHECK/UPDATENAME 跨文件標準名更新）─────────
# 每次呼叫用不同的 source_doc_id／chunk_index，模擬「不同文件/不同 chunk 各
# 提及一次」——HAS_ENTITY 邊以 (chunk, entity, surface_form) 為 MERGE 鍵，
# 同一 chunk 內重複提及同一別名不會累加次數，這是刻意的頻率語意（見
# services/svo_service.py::_merge_chunk_mention 的說明）。

@pytest.mark.asyncio
async def test_merge_entity_without_chunk_info_skips_has_entity_and_keeps_name():
    """未提供 chunk 追溯資訊時，退化為單純 MERGE 節點，不做頻率提升判斷。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()

    final_name = await svc.merge_entity(driver, kg_id, "泰國", "LOCATION", "泰國")

    assert final_name == "泰國"
    assert (str(kg_id), "泰國") in driver.entities
    assert driver.has_entity_edges == {}


@pytest.mark.asyncio
async def test_merge_entity_creates_new_node_with_initial_alias_count():
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    doc_id = uuid4()

    final_name = await svc.merge_entity(
        driver, kg_id, "泰國", "LOCATION", "泰國",
        source_doc_id=doc_id, source_svo_chunk_index=1,
    )

    assert final_name == "泰國"
    assert driver.entities[(str(kg_id), "泰國")]["aliases"] == ["泰國"]


@pytest.mark.asyncio
async def test_merge_entity_recheck_promotes_more_frequent_surface_form():
    """對應 3.4 §b RECHECK：跨文件累積次數超過現有 Entity.name 時才更新標準名。

    「I-35」與「Interstate Highway 35」字面幾乎無重疊，須靠 cosine 相似度
    （這裡用合成向量模擬）才會被識別為同一實體，之後才輪到頻率累積與提升。
    """
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding(similar_to={"I-35": "Interstate Highway 35"})

    await svc.merge_entity(
        driver, kg_id, "Interstate Highway 35", "LOCATION", "Interstate Highway 35",
        source_doc_id=uuid4(), source_svo_chunk_index=1,
        embedding_provider=embedding,
    )
    final_name = "Interstate Highway 35"
    for i in range(5):
        final_name = await svc.merge_entity(
            driver, kg_id, "I-35", "LOCATION", "I-35",
            source_doc_id=uuid4(), source_svo_chunk_index=i + 2,
            embedding_provider=embedding,
        )

    assert final_name == "I-35"
    assert (str(kg_id), "Interstate Highway 35") not in driver.entities
    assert sorted(driver.entities[(str(kg_id), "I-35")]["aliases"]) == sorted(
        ["I-35", "Interstate Highway 35"]
    )


@pytest.mark.asyncio
async def test_merge_entity_frequency_counts_distinct_documents_not_chunks():
    """對應 2026-07-21 修訂：一份文件切成再多 chunk，都只算一票——不應因為
    單一文件的 chunk 數量多，就讓它選中的別名在跨文件頻率上灌票。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding(similar_to={"I-35": "Interstate Highway 35"})

    # 文件 A：10 個 chunk 都用「I-35」（模擬 §a 已把該文件內的別名收斂成
    # 「I-35」——例如該文件內「I-35」本身就是最長的形式）
    doc_a = uuid4()
    for i in range(10):
        await svc.merge_entity(
            driver, kg_id, "I-35", "LOCATION", "I-35",
            source_doc_id=doc_a, source_svo_chunk_index=i + 1,
            embedding_provider=embedding,
        )

    # 文件 B：只有 1 個 chunk，用「Interstate Highway 35」
    final_name = await svc.merge_entity(
        driver, kg_id, "Interstate Highway 35", "LOCATION", "Interstate Highway 35",
        source_doc_id=uuid4(), source_svo_chunk_index=1,
        embedding_provider=embedding,
    )

    # 若按邊數（chunk 數）計，「I-35」會以 10:1 遙遙領先；但按獨立文件數計，
    # 兩者應打平（各 1 份文件），此時比長度，「Interstate Highway 35」較長勝出。
    assert final_name == "Interstate Highway 35"


@pytest.mark.asyncio
async def test_merge_entity_does_not_promote_rare_long_form_over_frequent_short_form():
    """對應使用者提出的「泰國 vs. 罕用正式全名」情境——單次出現的長字面不應
    覆蓋已累積 50 次的常用名稱。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()

    final_name = "泰國"
    for i in range(50):
        final_name = await svc.merge_entity(
            driver, kg_id, "泰國", "LOCATION", "泰國",
            source_doc_id=uuid4(), source_svo_chunk_index=i + 1,
        )
    final_name = await svc.merge_entity(
        driver, kg_id, "泰國", "LOCATION", "泰國全名",
        source_doc_id=uuid4(), source_svo_chunk_index=51,
    )

    assert final_name == "泰國"


@pytest.mark.asyncio
async def test_merge_triples_to_graph_merges_alias_into_existing_entity():
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    doc_id = uuid4()

    first = SVOTriple(
        subject="台積電", rel_type="PRODUCES", verb="生產", object="晶片",
        source_doc_id=doc_id, source_svo_chunk_index=1,
    )
    second = SVOTriple(
        subject="台積電公司", rel_type="PRODUCES", verb="生產", object="晶片",
        source_doc_id=doc_id, source_svo_chunk_index=2,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [first])
    await svc.merge_triples_to_graph(driver, kg_id, [second])

    # 「台積電公司」透過編輯距離規則併入既有的「台積電」節點，不應各自獨立成節點；
    # 兩者出現次數打平（各 1 次）時依長度次規則，較長的「台積電公司」勝出成為標準名——
    # 這是 PK 規則本身的預期行為，重點是「只剩一個實體」而非兩個（第二筆關係處理時才
    # 觸發改名，第一筆關係建立當下用的仍是改名前的參數，與真實 Neo4j 節點參照一致，
    # 只是本測試替身以字串記錄關係參數、不模擬節點物件參照，此處不特別驗證）。
    entity_names = [name for (kid, name) in driver.entities if kid == str(kg_id)]
    assert "台積電" not in entity_names
    assert "台積電公司" in entity_names
    assert len(driver.relationships) == 2
    assert {key[2] for key in driver.relationships if key[0] == str(kg_id)} <= {"台積電", "台積電公司"}


@pytest.mark.asyncio
async def test_merge_triples_to_graph_collapses_identical_fact_into_one_edge_with_citations():
    """對應 2026-07-22 使用者確認：即使兩次抽取來自完全不重疊的 chunk
    （這裡刻意用第 3 塊與第 50 塊模擬），只要 (subject, rel_type, object)
    相同，就該收斂成同一條邊，來源清單累積兩筆引用，而不是產生兩條邊。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()

    first = SVOTriple(
        subject="馬斯克", rel_type="CREATED_BY", verb="創立", object="SpaceX",
        source_doc_id=uuid4(), source_svo_chunk_index=3,
        source_sentence_start=10, source_sentence_end=10,
    )
    second = SVOTriple(
        subject="馬斯克", rel_type="CREATED_BY", verb="創辦", object="SpaceX",
        source_doc_id=uuid4(), source_svo_chunk_index=50,
        source_sentence_start=210, source_sentence_end=210,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [first, second])

    keys = [k for k in driver.relationships if k[0] == str(kg_id)]
    assert len(keys) == 1
    citations = json.loads(driver.relationships[keys[0]]["citations_json"])
    assert len(citations) == 2
    assert {c["source_svo_chunk_index"] for c in citations} == {3, 50}
    assert {c["verb"] for c in citations} == {"創立", "創辦"}


@pytest.mark.asyncio
async def test_merge_entity_records_has_entity_edge_with_surface_form():
    """對應 3.4 §b RECORD3B：HAS_ENTITY 邊需記錄本次提及的原文字面。

    `name`／`surface_form` 在實際呼叫路徑（`merge_triples_to_graph`）永遠是
    同一個字串（皆為 `triple.subject`／`triple.object`），這裡如實反映該用法；
    不對稱的組合（`resolve_entity_name` 解析出的既有實體 vs. 這次提及的別名
    字面不同）已由 `test_merge_entity_recheck_promotes_more_frequent_surface_form`
    覆蓋。
    """
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    doc_id = uuid4()

    await svc.merge_entity(
        driver, kg_id, "Richard Stone", "PERSON", "Richard Stone",
        source_doc_id=doc_id, source_svo_chunk_index=1,
    )

    edge_keys = [k for k in driver.has_entity_edges if k[0] == str(kg_id)]
    assert len(edge_keys) == 1
    _, chunk_key, entity_name, surface_form = edge_keys[0]
    assert chunk_key == (str(kg_id), str(doc_id), 1)
    assert entity_name == "Richard Stone"
    assert surface_form == "Richard Stone"


# ── Chunk 向量化（切塊當下順便計算，2026-07-22 使用者提出）────────────────

@pytest.mark.asyncio
async def test_embed_svo_chunks_without_provider_is_noop():
    driver = FakeDriver()
    from services.svo_chunking import build_svo_chunks

    chunks = build_svo_chunks(["一。", "二。"], ["一。", "二。"])
    await svc.embed_svo_chunks(driver, uuid4(), "note.md", chunks, None)

    assert driver.calls == []


@pytest.mark.asyncio
async def test_embed_svo_chunks_writes_one_vector_per_chunk():
    driver = FakeDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding()
    from services.svo_chunking import build_svo_chunks

    sentences = [f"第{i}句。" for i in range(1, 12)]
    chunks = build_svo_chunks(sentences, sentences)  # 產生 3 個重疊 chunk

    await svc.embed_svo_chunks(driver, kg_id, "note.md", chunks, embedding)

    assert len(driver.calls) == len(chunks)
    for (query, params), chunk in zip(driver.calls, chunks):
        assert "c.embedding" in query
        assert params["kg_id"] == str(kg_id)
        assert params["source"] == "note.md"
        assert params["chunk_index"] == chunk.index
        assert params["chunk_file"] == chunk.filename
        assert len(params["embedding"]) == embedding.dim


@pytest.mark.asyncio
async def test_create_chunk_vector_index_without_driver_is_noop():
    await svc.create_chunk_vector_index(None)  # 不應拋出例外


@pytest.mark.asyncio
async def test_bfs_query_maps_records_using_latest_citation():
    """事實層級去重後，`bfs_query` 改讀 `citations_json`，取最後一筆引用
    當作這條邊的代表來源——挑選哪幾筆最相關留給回答階段的向量篩選（不在
    本次範圍），這裡只驗證欄位不會靜默變成 null。"""
    doc_id = uuid4()
    citations_json = json.dumps([
        {
            "source_doc_id": str(doc_id),
            "source_svo_chunk_index": 1,
            "source_svo_chunk_file": "svo-chunk-001-of-001.md",
            "source_sentence_start": 1,
            "source_sentence_end": 2,
            "verb": "導致",
            "confidence": 3,
        }
    ])
    driver = FakeDriver(records=[
        FakeRecord(
            subject="A",
            subject_type="概念",
            rel_type="CAUSES",
            confidence=3,
            citations_json=citations_json,
            object="B",
            object_type="概念",
        )
    ])

    triples = await svc.bfs_query(driver, uuid4(), ["A"], hops=2)

    assert len(triples) == 1
    assert triples[0].source_doc_id == doc_id
    assert triples[0].source_sentence_start == 1
    assert triples[0].verb == "導致"
