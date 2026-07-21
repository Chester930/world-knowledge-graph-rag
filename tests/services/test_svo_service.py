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
        self.relationships: list[dict] = []
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
            kg_id, entity_name = params["kg_id"], params["entity_name"]
            counts: dict[str, int] = {}
            for (kid, _chunk_key, ename, surface_form) in self.has_entity_edges:
                if kid == kg_id and ename == entity_name:
                    counts[surface_form] = counts.get(surface_form, 0) + 1
            records = [{"alias": alias, "freq": freq} for alias, freq in counts.items()]
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

        if "MERGE (s)-[r:" in stripped:
            self.relationships.append(dict(params))
            return FakeResult([])

        return FakeResult([])


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
async def test_merge_triples_to_graph_passes_sentence_trace_fields():
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

    rel_calls = [(q, p) for q, p in driver.calls if "`CAUSES`" in q]
    assert len(rel_calls) == 1
    query, params = rel_calls[0]
    assert params["kg_id"] == str(kg_id)
    assert params["subject"] == "A"
    assert params["object"] == "B"
    assert params["source_doc_id"] == str(doc_id)
    assert params["source_svo_chunk_index"] == 2
    assert params["source_sentence_start"] == 5
    assert params["source_sentence_end"] == 7


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
    assert {rel["subject"] for rel in driver.relationships} <= {"台積電", "台積電公司"}


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


@pytest.mark.asyncio
async def test_bfs_query_maps_records_to_triples():
    doc_id = uuid4()
    driver = FakeDriver(records=[
        FakeRecord(
            subject="A",
            subject_type="概念",
            rel_type="CAUSES",
            verb="導致",
            object="B",
            object_type="概念",
            confidence=3,
            source_doc_id=str(doc_id),
            source_svo_chunk_index=1,
            source_svo_chunk_file="svo-chunk-001-of-001.md",
            source_sentence_start=1,
            source_sentence_end=2,
        )
    ])

    triples = await svc.bfs_query(driver, uuid4(), ["A"], hops=2)

    assert len(triples) == 1
    assert triples[0].source_doc_id == doc_id
    assert triples[0].source_sentence_start == 1
