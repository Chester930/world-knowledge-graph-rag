import json
import re
from uuid import uuid4

import pytest
from neo4j.exceptions import ConstraintError

from core import config
from core.constants import FACT_SEARCH_CANDIDATE_MULTIPLIER, SVO_REL_TYPES
from models.knowledge_graph import SVOTriple
from services import document_record_service, ingestion_service, svo_service as svc
from services import task_queue_service
from services.svo_chunking import SVOChunk


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

    async def encode(self, text: str) -> list[float]:
        key = self._similar_to.get(text, text)
        if key not in self._index:
            self._index[key] = len(self._index)
        idx = self._index[key] % self.dim
        vec = [0.0] * self.dim
        vec[idx] = 1.0
        return vec

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.encode(t) for t in texts]


class SequencedFakeLLM:
    """依呼叫順序回傳不同回應的 LLM 替身——用於同時涉及「LLM_SVO 抽取」與
    「ESCALATE3 仲裁」兩次獨立呼叫的測試情境；`FakeLLM` 的單一 `payload`
    無法讓 `generate_json`（抽取）與 `generate`（仲裁）回傳不同內容。"""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)

    async def stream(self, prompt: str):
        yield self._responses[0]

    async def generate_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0)


class TypeDescriptionFakeEmbedding:
    """供 SIM／COMPARE／ESCALATE3 測試使用：只精確控制指定文字的向量方向，
    其餘（未列出的）文字一律回傳 `default` 向量。刻意不沿用 `FakeEmbedding`
    的雜湊索引方式——35 個真實描述句彼此雜湊碰撞（`idx % dim`）的機率不可忽略，
    會讓「哪個型別是最相似者」的測試斷言變得不可靠。

    `model_name` 每個實例各自不同（遞增計數器）——`classify_relation_by_embedding()`
    以 `model_name` 為 key 快取型別描述句 embedding（見 svo_service.py
    `_type_description_embeddings` docstring），若多個測試共用同一個
    `model_name` 字串，會讀到前一個測試殘留的快取內容，測試彼此汙染。
    """

    _counter = 0

    dim = 3

    def __init__(self, vectors: dict[str, list[float]], default: list[float]):
        self._vectors = vectors
        self._default = default
        TypeDescriptionFakeEmbedding._counter += 1
        self.model_name = f"fake-type-desc-embedding-{TypeDescriptionFakeEmbedding._counter}"

    async def encode(self, text: str) -> list[float]:
        return self._vectors.get(text, self._default)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors.get(t, self._default) for t in texts]


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
        self.facts: list[dict] = []  # 3.1.4 §a：每筆 CREATE (f:Fact ...) 呼叫的 params，供斷言用
        self.queries: list[str] = []

    async def execute_query(self, query: str, **params):
        self.queries.append(query)
        stripped = query.strip()

        if "CREATE (f:Fact" in stripped:
            self.facts.append(params)
            return FakeResult([])

        if stripped.startswith("MATCH (e:Entity {kg_id: $kg_id}) RETURN e.name"):
            kg_id = params["kg_id"]
            records = [
                {"name": name, "type": data["type"], "name_embedding": data.get("name_embedding")}
                for (kid, name), data in self.entities.items()
                if kid == kg_id
            ]
            return FakeResult(records)

        if stripped.startswith("MERGE (e:Entity {kg_id: $kg_id, name: $name}) ON CREATE SET"):
            key = (params["kg_id"], params["name"])
            self.entities.setdefault(
                key, {"type": params["entity_type"], "name_embedding": params.get("name_embedding")}
            )
            return FakeResult([])

        if stripped.startswith("MERGE (c:Chunk"):
            kg_id = params["kg_id"]
            entity_key = (kg_id, params["entity_name"])
            self.entities.setdefault(
                entity_key, {"type": params["entity_type"], "name_embedding": params.get("name_embedding")}
            )
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
            self.entities[new_key] = {
                "type": existing["type"],
                "aliases": params["aliases"],
                "name_embedding": existing.get("name_embedding"),
            }
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
async def test_extract_svo_triples_parses_valid_json_and_downgrades_invalid_rel_type():
    """3.1.3 REJECT：不合法 rel_type 退回 RELATED_TO 兜底，三元組本身保留
    （不可靜默丟棄整條事實），見 03_系統設計與方法論.md § 3.1.3。"""
    llm = FakeLLM("""
    {"triples":[
      {"subject":"A","rel_type":"CAUSES","verb":"導致","object":"B","confidence":4},
      {"subject":"X","rel_type":"NOT_ALLOWED","verb":"關係","object":"Y","confidence":3}
    ]}
    """)

    triples = await svc.extract_svo_triples("A 導致 B。", llm)

    assert len(triples) == 2
    assert triples[0].subject == "A"
    assert triples[0].rel_type == "CAUSES"
    assert triples[1].subject == "X"
    assert triples[1].rel_type == "RELATED_TO"
    assert triples[1].verb == "關係"
    assert "合法 rel_type" in llm.prompts[0]


@pytest.mark.asyncio
async def test_extract_svo_triples_prompt_instructs_concise_entity_names():
    """2026-08-24（見 docs/報告/17）：真實測試發現 SVO 抽取常把整段條文子句
    當成 subject／object（例如 69 字的完整句子），導致 `_find_seed_entities()`
    的字面比對與跨文件實體共用皆完全失效。prompt 須明確要求簡潔、可重複使用
    的名詞（附反例／正例），不能只靠 entity_type 參考清單間接約束長度。"""
    llm = FakeLLM('{"triples":[]}')

    await svc.extract_svo_triples("任意文本。", llm)

    prompt = llm.prompts[0]
    assert "簡潔" in prompt and "可重複使用" in prompt
    assert "不可整段抄錄條文子句或完整句子" in prompt


@pytest.mark.asyncio
async def test_extract_svo_triples_without_provider_returns_empty_list():
    assert await svc.extract_svo_triples("A 導致 B。") == []


# ── SIM／COMPARE／ESCALATE3（3.1.3 主圖，`SVO_REL_TYPE_DESCRIPTIONS` 描述句比對）──

def test_svo_rel_type_descriptions_keys_match_svo_rel_types():
    """`SVO_REL_TYPE_DESCRIPTIONS` 的 key 需與 `SVO_REL_TYPES` 完全一致
    （見 core/constants.py 兩者的 docstring 互相校驗承諾）。"""
    assert set(svc.SVO_REL_TYPE_DESCRIPTIONS) == svc.SVO_REL_TYPES


@pytest.mark.asyncio
async def test_classify_relation_by_embedding_returns_top_cosine_match():
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )

    best_type, score = await svc.classify_relation_by_embedding("導致", embedding)

    assert best_type == "CAUSES"
    assert score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_extract_svo_triples_compare_agrees_skips_escalation():
    """COMPARE 一致（embedding 最相似型別＝LLM 自報值，且分數 ≥ 門檻）時，
    直接採用 LLM 自報值，不觸發 ESCALATE3 第二次呼叫。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"CAUSES","verb":"導致","object":"B","confidence":4}]}'
    ])

    triples = await svc.extract_svo_triples("A 導致 B。", llm, embedding_provider=embedding)

    assert triples[0].rel_type == "CAUSES"
    assert len(llm.prompts) == 1  # 沒有觸發 ESCALATE3
    assert triples[0].verb_embedding is None  # 3.1.3 §a-1：已有明確型別不需存 verb embedding


@pytest.mark.asyncio
async def test_extract_svo_triples_compare_disagrees_escalates_and_adopts_embedding_candidate():
    """COMPARE 不一致（embedding 最相似型別≠LLM 自報值）時交由 ESCALATE3 仲裁，
    LLM 確認 embedding 建議的候選則採用該候選。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"RELATED_TO","verb":"導致","object":"B","confidence":2}]}',
        "CAUSES",
    ])

    triples = await svc.extract_svo_triples("A 導致 B。", llm, embedding_provider=embedding)

    assert triples[0].rel_type == "CAUSES"
    assert len(llm.prompts) == 2
    assert "RELATED_TO" in llm.prompts[1] and "CAUSES" in llm.prompts[1]


@pytest.mark.asyncio
async def test_extract_svo_triples_escalate3_confirms_original_llm_answer():
    """ESCALATE3 仲裁後確認原答案（而非 embedding 建議的候選）時，維持 LLM 自報值。"""
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],  # 35 個型別描述句皆與 verb 不相似，分數低於門檻
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"CAUSES","verb":"導致","object":"B","confidence":3}]}',
        "CAUSES",
    ])

    triples = await svc.extract_svo_triples("A 導致 B。", llm, embedding_provider=embedding)

    assert triples[0].rel_type == "CAUSES"
    assert len(llm.prompts) == 2


@pytest.mark.asyncio
async def test_extract_svo_triples_escalate3_neither_falls_back_to_related_to():
    """ESCALATE3 判定「皆非」（候選新類別）時，先退回 RELATED_TO 兜底，
    三元組本身仍保留（見 `_reconcile_rel_type` docstring）。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"MANNER_OF","verb":"導致","object":"B","confidence":2}]}',
        "皆非",
    ])

    triples = await svc.extract_svo_triples("A 導致 B。", llm, embedding_provider=embedding)

    assert triples[0].rel_type == "RELATED_TO"
    assert triples[0].subject == "A"  # 三元組本身保留，不因型別降級而丟棄
    # 3.1.3 §a-1 BACKFILL：降級為 RELATED_TO 時應保留 verb embedding，
    # 供日後 EXPAND 核准新型別時的回溯重分類使用。
    assert triples[0].verb_embedding == [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_extract_svo_triples_escalate3_neither_adds_candidate_to_expand_pool(tmp_path):
    """對應 P2-1（2026-07-27）：ESCALATE3 判定「皆非」時，提供 kg_id／
    calibration_db_path 應把該動詞連同其 embedding 記入 EXPAND 候選池，
    供治理 Worker（services/expand_worker.py）之後判斷是否構成新類別。"""
    from services import expand_governance_service

    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"MANNER_OF","verb":"導致","object":"B","confidence":2}]}',
        "皆非",
    ])
    db_path = tmp_path / "task_queue.db"

    await svc.extract_svo_triples(
        "A 導致 B。", llm, embedding_provider=embedding, kg_id="kg-1", calibration_db_path=db_path,
    )

    candidates = expand_governance_service.pending_candidates(db_path, "kg-1")
    assert len(candidates) == 1
    assert candidates[0]["verb"] == "導致"
    assert candidates[0]["verb_embedding"] == [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_extract_svo_triples_escalate3_neither_skips_expand_pool_without_kg_id(tmp_path):
    """未提供 kg_id／calibration_db_path 時完全不記錄，向後相容。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"MANNER_OF","verb":"導致","object":"B","confidence":2}]}',
        "皆非",
    ])
    db_path = tmp_path / "task_queue.db"

    await svc.extract_svo_triples("A 導致 B。", llm, embedding_provider=embedding)

    assert not db_path.exists()


# ── resolve_query_relation_type（§ 3.2 §c 查詢時關係連結，2026-08-18 定案）──

@pytest.mark.asyncio
async def test_resolve_query_relation_type_high_score_assigns_directly():
    """最高分 ≥ QSIM_ASSIGN_THRESHOLD 時直接採用，不呼叫 LLM。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致 B": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = FakeLLM("不應被呼叫")

    result = await svc.resolve_query_relation_type("導致 B", embedding, llm_provider=llm)

    assert result == "CAUSES"
    assert llm.prompts == []


@pytest.mark.asyncio
async def test_resolve_query_relation_type_gray_zone_llm_confirms():
    """灰色地帶且 LLM 確認候選型別時採用該型別。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    gray_zone_score = (svc.QSIM_ASSIGN_THRESHOLD + svc.QSIM_ESCALATE_LOW_THRESHOLD) / 2
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [gray_zone_score, (1 - gray_zone_score**2) ** 0.5, 0.0],
                 causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 0.0, 1.0],
    )
    llm = FakeLLM("是")

    result = await svc.resolve_query_relation_type("導致", embedding, llm_provider=llm)

    assert result == "CAUSES"
    assert len(llm.prompts) == 1
    assert "CAUSES" in llm.prompts[0]


@pytest.mark.asyncio
async def test_resolve_query_relation_type_gray_zone_llm_rejects_returns_none():
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    gray_zone_score = (svc.QSIM_ASSIGN_THRESHOLD + svc.QSIM_ESCALATE_LOW_THRESHOLD) / 2
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"某措辭": [gray_zone_score, (1 - gray_zone_score**2) ** 0.5, 0.0],
                 causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 0.0, 1.0],
    )
    llm = FakeLLM("否")

    result = await svc.resolve_query_relation_type("某措辭", embedding, llm_provider=llm)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_query_relation_type_gray_zone_without_llm_provider_returns_none():
    """灰色地帶但沒有 llm_provider 時視為無法確認，直接回傳 None，不猜測。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    gray_zone_score = (svc.QSIM_ASSIGN_THRESHOLD + svc.QSIM_ESCALATE_LOW_THRESHOLD) / 2
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"某措辭": [gray_zone_score, (1 - gray_zone_score**2) ** 0.5, 0.0],
                 causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 0.0, 1.0],
    )

    result = await svc.resolve_query_relation_type("某措辭", embedding, llm_provider=None)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_query_relation_type_below_low_threshold_skips_llm_call():
    """低於 QSIM_ESCALATE_LOW_THRESHOLD 時直接判無 match，不浪費一次 LLM 呼叫
    （即使有提供 llm_provider）。所有 35 個型別描述句皆未指定、共用 default
    向量，與查詢措辭的向量正交（cosine=0），確保分數低於門檻。"""
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"完全不相關的措辭": [0.0, 0.0, 1.0]}, default=[1.0, 0.0, 0.0]
    )
    llm = FakeLLM("不應被呼叫")

    result = await svc.resolve_query_relation_type("完全不相關的措辭", embedding, llm_provider=llm)

    assert result is None
    assert llm.prompts == []


# ── _relationship_type（Cypher 注入防護，見 P2-1 docstring）─────────────────

def test_relationship_type_accepts_svo_rel_types_member():
    assert svc._relationship_type("CAUSES") == "`CAUSES`"


def test_relationship_type_accepts_safe_dynamic_type_name():
    """對應 EXPAND 治理機制動態核准的新型別（不在 SVO_REL_TYPES 內，但格式安全）。"""
    assert svc._relationship_type("INVESTS_IN") == "`INVESTS_IN`"


def test_relationship_type_rejects_unsafe_characters():
    """Neo4j 關係型別無法參數化，格式不安全的字串必須拒絕，避免 Cypher 注入。"""
    with pytest.raises(ValueError):
        svc._relationship_type("CAUSES`]-() MATCH (n) DETACH DELETE n //")


def test_relationship_type_rejects_lowercase():
    with pytest.raises(ValueError):
        svc._relationship_type("invests_in")


@pytest.mark.asyncio
async def test_extract_svo_triples_without_embedding_provider_skips_reconciliation():
    """未提供 `embedding_provider` 時，維持先前版本行為——直接採用 LLM 自報值，
    不執行 SIM／COMPARE／ESCALATE3（向後相容）。"""
    llm = FakeLLM(
        '{"triples":[{"subject":"A","rel_type":"CAUSES","verb":"導致","object":"B","confidence":4}]}'
    )

    triples = await svc.extract_svo_triples("A 導致 B。", llm)

    assert triples[0].rel_type == "CAUSES"
    assert len(llm.prompts) == 1
    assert triples[0].verb_embedding is None


# ── SIM 學習/校正機制：ESCALATE3 仲裁事件記錄 ────────────────────────────────

@pytest.mark.asyncio
async def test_extract_svo_triples_logs_escalation_when_kg_id_and_db_path_provided(tmp_path):
    """真正觸發 ESCALATE3 時，提供 kg_id／calibration_db_path 應記錄一筆仲裁
    事件，供 SIM 學習/校正機制計算一致率。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"RELATED_TO","verb":"導致","object":"B","confidence":2}]}',
        "CAUSES",
    ])
    db_path = tmp_path / "task_queue.db"

    triples = await svc.extract_svo_triples(
        "A 導致 B。", llm, embedding_provider=embedding,
        kg_id="kg-1", calibration_db_path=db_path,
    )

    assert triples[0].rel_type == "CAUSES"
    from services import sim_calibration_service
    assert sim_calibration_service.sim_agreement_rate(db_path, "CAUSES", window=1) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_extract_svo_triples_does_not_log_without_kg_id_and_db_path(tmp_path):
    """未提供 kg_id／calibration_db_path 時完全不記錄，向後相容。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"RELATED_TO","verb":"導致","object":"B","confidence":2}]}',
        "CAUSES",
    ])
    db_path = tmp_path / "task_queue.db"

    await svc.extract_svo_triples("A 導致 B。", llm, embedding_provider=embedding)

    assert not db_path.exists()


@pytest.mark.asyncio
async def test_extract_svo_triples_does_not_log_when_compare_agrees(tmp_path):
    """COMPARE 一致、未觸發 ESCALATE3 時不記錄——沒有「最終仲裁結果」可比對。"""
    causes_desc = svc.SVO_REL_TYPE_DESCRIPTIONS["CAUSES"]
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"導致": [1.0, 0.0, 0.0], causes_desc: [1.0, 0.0, 0.0]},
        default=[0.0, 1.0, 0.0],
    )
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"A","rel_type":"CAUSES","verb":"導致","object":"B","confidence":4}]}'
    ])
    db_path = tmp_path / "task_queue.db"

    await svc.extract_svo_triples(
        "A 導致 B。", llm, embedding_provider=embedding,
        kg_id="kg-1", calibration_db_path=db_path,
    )

    from services import sim_calibration_service
    assert sim_calibration_service.sim_agreement_rate(db_path, "CAUSES", window=1) is None


# ── 3.1.3 §a-1 BACKFILL：verb_embedding 持久化與回溯重分類 ───────────────────

@pytest.mark.asyncio
async def test_merge_triples_to_graph_stores_verb_embedding_for_related_to_edges():
    """RELATED_TO 兜底的邊需存 verb_embedding，供日後 EXPAND 核准新型別時的
    向量索引查詢使用（見 backfill_related_to_edges）。"""
    driver = FakeDriver()
    kg_id = uuid4()
    triple = SVOTriple(
        subject="A", rel_type="RELATED_TO", verb="有點像",
        object="B", verb_embedding=[0.1, 0.2, 0.3],
    )

    await svc.merge_triples_to_graph(driver, kg_id, [triple])

    set_calls = [(q, p) for q, p in driver.calls if "SET r.citations_json = $citations_json" in q]
    assert len(set_calls) == 1
    query, params = set_calls[0]
    assert "r.verb_embedding" in query
    assert params["verb_embedding"] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_merge_triples_to_graph_skips_verb_embedding_for_typed_edges():
    """已有明確型別的邊不需要 verb_embedding，省下多餘的儲存。"""
    driver = FakeDriver()
    kg_id = uuid4()
    triple = SVOTriple(subject="A", rel_type="CAUSES", verb="導致", object="B")

    await svc.merge_triples_to_graph(driver, kg_id, [triple])

    set_calls = [(q, p) for q, p in driver.calls if "SET r.citations_json = $citations_json" in q]
    query, params = set_calls[0]
    assert "r.verb_embedding" not in query
    assert "verb_embedding" not in params


@pytest.mark.asyncio
async def test_create_related_to_vector_index_without_driver_is_noop():
    await svc.create_related_to_vector_index(None)  # 不應拋出例外


@pytest.mark.asyncio
async def test_create_related_to_vector_index_issues_create_vector_index_query():
    driver = FakeDriver()

    await svc.create_related_to_vector_index(driver, dim=384)

    assert len(driver.calls) == 1
    query, params = driver.calls[0]
    assert "CREATE VECTOR INDEX related_to_verb_embedding" in query
    assert "FOR ()-[r:RELATED_TO]-() ON r.verb_embedding" in query
    assert params["dim"] == 384


class BackfillFakeDriver:
    """模擬 `db.index.vector.queryRelationships` 查詢結果，並記錄所有呼叫
    （含向量查詢本身與後續 DELETE／CREATE），供 `backfill_related_to_edges()`
    測試使用。"""

    def __init__(self, vector_query_records):
        self._vector_query_records = vector_query_records
        self.vector_query_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.create_calls: list[tuple] = []

    async def execute_query(self, query: str, **params):
        stripped = query.strip()
        if "db.index.vector.queryRelationships" in stripped:
            self.vector_query_calls.append(params)
            return FakeResult(self._vector_query_records)
        if "DELETE r" in stripped:
            self.delete_calls.append(params)
            return FakeResult([])
        if stripped.startswith("MATCH (s:Entity") and "CREATE (s)-[r:" in stripped:
            self.create_calls.append((query, params))
            return FakeResult([])
        return FakeResult([])


@pytest.mark.asyncio
async def test_backfill_related_to_edges_rewrites_matched_edges_to_new_type():
    """LLM 確認關卡回答「是」時，候選邊才真的升級為新型別。"""
    driver = BackfillFakeDriver(
        vector_query_records=[
            {"subject": "A", "object": "B", "citations_json": '[{"verb":"有點像"}]', "confidence": 3}
        ]
    )
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.2, 0.4, 0.6])
    llm = FakeLLM("是")
    kg_id = uuid4()

    count = await svc.backfill_related_to_edges(
        driver, kg_id, "MANNER_OF", "A 是 B 這個較一般行為的特定實現方式", embedding,
        llm_provider=llm,
    )

    assert count == 1
    assert len(driver.delete_calls) == 1
    assert driver.delete_calls[0]["subject"] == "A"
    assert driver.delete_calls[0]["object"] == "B"
    assert len(driver.create_calls) == 1
    create_query, create_params = driver.create_calls[0]
    assert "r:`MANNER_OF`" in create_query
    assert create_params["citations_json"] == '[{"verb":"有點像"}]'
    assert create_params["confidence"] == 3
    assert "A" in llm.prompts[0] and "有點像" in llm.prompts[0] and "B" in llm.prompts[0]
    assert "MANNER_OF" in llm.prompts[0]


@pytest.mark.asyncio
async def test_backfill_related_to_edges_without_llm_provider_never_rewrites():
    """未提供 llm_provider 時，為安全起見一律不改寫任何邊——即使有候選命中，
    也不會退回「純 cosine 分數即可改寫」的舊行為。"""
    driver = BackfillFakeDriver(
        vector_query_records=[
            {"subject": "A", "object": "B", "citations_json": '[{"verb":"有點像"}]', "confidence": 3}
        ]
    )
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.2, 0.4, 0.6])
    kg_id = uuid4()

    count = await svc.backfill_related_to_edges(
        driver, kg_id, "MANNER_OF", "A 是 B 這個較一般行為的特定實現方式", embedding
    )

    assert count == 0
    assert driver.delete_calls == []
    assert driver.create_calls == []


@pytest.mark.asyncio
async def test_backfill_related_to_edges_skips_candidate_when_llm_rejects():
    driver = BackfillFakeDriver(
        vector_query_records=[
            {"subject": "A", "object": "B", "citations_json": '[{"verb":"有點像"}]', "confidence": 3}
        ]
    )
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.2, 0.4, 0.6])
    llm = FakeLLM("否")
    kg_id = uuid4()

    count = await svc.backfill_related_to_edges(
        driver, kg_id, "MANNER_OF", "A 是 B 這個較一般行為的特定實現方式", embedding,
        llm_provider=llm,
    )

    assert count == 0
    assert driver.delete_calls == []
    assert driver.create_calls == []


@pytest.mark.asyncio
async def test_backfill_related_to_edges_returns_zero_when_no_matches():
    driver = BackfillFakeDriver(vector_query_records=[])
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.2, 0.4, 0.6])
    kg_id = uuid4()

    count = await svc.backfill_related_to_edges(
        driver, kg_id, "MANNER_OF", "A 是 B 這個較一般行為的特定實現方式", embedding
    )

    assert count == 0
    assert driver.delete_calls == []
    assert driver.create_calls == []


@pytest.mark.asyncio
async def test_backfill_related_to_edges_passes_threshold_and_kg_id_to_query():
    driver = BackfillFakeDriver(vector_query_records=[])
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.2, 0.4, 0.6])
    kg_id = uuid4()

    await svc.backfill_related_to_edges(
        driver, kg_id, "MANNER_OF", "A 是 B 這個較一般行為的特定實現方式", embedding
    )

    assert len(driver.vector_query_calls) == 1
    params = driver.vector_query_calls[0]
    assert params["kg_id"] == str(kg_id)
    assert params["threshold"] == svc.COMPARE_COSINE_THRESHOLD
    assert params["query_vector"] == [0.2, 0.4, 0.6]


class MissingEmbeddingFakeDriver:
    """模擬「查詢缺漏 verb_embedding 的 RELATED_TO 邊」結果，並記錄查詢本身與
    後續 SET 呼叫，供 `backfill_missing_verb_embeddings()` 測試使用。"""

    def __init__(self, records):
        self._records = records
        self.query_calls: list[dict] = []
        self.set_calls: list[dict] = []

    async def execute_query(self, query: str, **params):
        stripped = query.strip()
        if "WHERE r.verb_embedding IS NULL" in stripped:
            self.query_calls.append(params)
            return FakeResult(self._records)
        if "SET r.verb_embedding" in stripped:
            self.set_calls.append(params)
            return FakeResult([])
        return FakeResult([])


@pytest.mark.asyncio
async def test_backfill_missing_verb_embeddings_fills_in_missing_embedding():
    driver = MissingEmbeddingFakeDriver(
        records=[
            {"subject": "A", "object": "B", "citations_json": '[{"verb":"有點像"}]'}
        ]
    )
    embedding = TypeDescriptionFakeEmbedding(vectors={"有點像": [0.5, 0.5, 0.0]}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    count = await svc.backfill_missing_verb_embeddings(driver, kg_id, embedding)

    assert count == 1
    assert len(driver.set_calls) == 1
    assert driver.set_calls[0]["subject"] == "A"
    assert driver.set_calls[0]["object"] == "B"
    assert driver.set_calls[0]["verb_embedding"] == [0.5, 0.5, 0.0]


@pytest.mark.asyncio
async def test_backfill_missing_verb_embeddings_returns_zero_when_no_gaps():
    driver = MissingEmbeddingFakeDriver(records=[])
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    count = await svc.backfill_missing_verb_embeddings(driver, kg_id, embedding)

    assert count == 0
    assert driver.set_calls == []


@pytest.mark.asyncio
async def test_backfill_missing_verb_embeddings_skips_edges_without_verb():
    """citations_json 為空陣列時（理論上不該發生）應跳過，不呼叫 embedding
    provider 或 SET，防禦性處理。"""
    driver = MissingEmbeddingFakeDriver(
        records=[{"subject": "A", "object": "B", "citations_json": "[]"}]
    )
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    count = await svc.backfill_missing_verb_embeddings(driver, kg_id, embedding)

    assert count == 0
    assert driver.set_calls == []


@pytest.mark.asyncio
async def test_backfill_missing_verb_embeddings_passes_kg_id_and_limit_to_query():
    driver = MissingEmbeddingFakeDriver(records=[])
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    await svc.backfill_missing_verb_embeddings(driver, kg_id, embedding, limit=50)

    assert len(driver.query_calls) == 1
    assert driver.query_calls[0]["kg_id"] == str(kg_id)
    assert driver.query_calls[0]["limit"] == 50


# ── backfill_entity_name_embeddings（3.1.4 DEDUP4 節點向量化，2026-08-03）──

class MissingEntityEmbeddingFakeDriver:
    """模擬「查詢缺漏 name_embedding 的 Entity 節點」結果，並記錄查詢本身與
    後續 SET 呼叫，供 `backfill_entity_name_embeddings()` 測試使用。"""

    def __init__(self, records):
        self._records = records
        self.query_calls: list[dict] = []
        self.set_calls: list[dict] = []

    async def execute_query(self, query: str, **params):
        stripped = query.strip()
        if "WHERE e.name_embedding IS NULL" in stripped:
            self.query_calls.append(params)
            return FakeResult(self._records)
        if "SET e.name_embedding" in stripped:
            self.set_calls.append(params)
            return FakeResult([])
        return FakeResult([])


@pytest.mark.asyncio
async def test_backfill_entity_name_embeddings_fills_in_missing_embedding():
    driver = MissingEntityEmbeddingFakeDriver(records=[{"name": "台積電"}])
    embedding = TypeDescriptionFakeEmbedding(vectors={"台積電": [0.5, 0.5, 0.0]}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    count = await svc.backfill_entity_name_embeddings(driver, kg_id, embedding)

    assert count == 1
    assert len(driver.set_calls) == 1
    assert driver.set_calls[0]["name"] == "台積電"
    assert driver.set_calls[0]["name_embedding"] == [0.5, 0.5, 0.0]


@pytest.mark.asyncio
async def test_backfill_entity_name_embeddings_handles_multiple_nodes():
    driver = MissingEntityEmbeddingFakeDriver(records=[{"name": "台積電"}, {"name": "鴻海"}])
    embedding = TypeDescriptionFakeEmbedding(
        vectors={"台積電": [1.0, 0.0, 0.0], "鴻海": [0.0, 1.0, 0.0]}, default=[0.0, 0.0, 1.0]
    )
    kg_id = uuid4()

    count = await svc.backfill_entity_name_embeddings(driver, kg_id, embedding)

    assert count == 2
    names_written = {call["name"] for call in driver.set_calls}
    assert names_written == {"台積電", "鴻海"}


@pytest.mark.asyncio
async def test_backfill_entity_name_embeddings_returns_zero_when_no_gaps():
    driver = MissingEntityEmbeddingFakeDriver(records=[])
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    count = await svc.backfill_entity_name_embeddings(driver, kg_id, embedding)

    assert count == 0
    assert driver.set_calls == []


@pytest.mark.asyncio
async def test_backfill_entity_name_embeddings_passes_kg_id_and_limit_to_query():
    driver = MissingEntityEmbeddingFakeDriver(records=[])
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    await svc.backfill_entity_name_embeddings(driver, kg_id, embedding, limit=50)

    assert len(driver.query_calls) == 1
    assert driver.query_calls[0]["kg_id"] == str(kg_id)
    assert driver.query_calls[0]["limit"] == 50


@pytest.mark.asyncio
async def test_backfill_entity_name_embeddings_default_limit_is_1000():
    """batch size 比 `backfill_missing_verb_embeddings()`（100）大，見函式
    docstring：單筆 Entity.name 遠短於 RELATED_TO 邊的完整 citations_json。"""
    driver = MissingEntityEmbeddingFakeDriver(records=[])
    embedding = TypeDescriptionFakeEmbedding(vectors={}, default=[0.0, 0.0, 1.0])
    kg_id = uuid4()

    await svc.backfill_entity_name_embeddings(driver, kg_id, embedding)

    assert driver.query_calls[0]["limit"] == 1000


# ── resolve_entity_type：核心庫（52 類）優先，查不到才查擴充庫（939 類）───────

def test_resolve_entity_type_matches_core_case_and_spacing_insensitive():
    assert svc.resolve_entity_type("local business") == "LOCAL_BUSINESS"
    assert svc.resolve_entity_type("Local_Business") == "LOCAL_BUSINESS"


def test_resolve_entity_type_exact_core_key_passthrough():
    assert svc.resolve_entity_type("PERSON") == "PERSON"


def test_resolve_entity_type_falls_back_to_extended_pool_when_not_in_core():
    """SoftwareApplication 不在核心 52 類，但是 schema.org 官方型別，
    應能從 data/schema_org_entity_types.json 擴充庫查到並回傳官方 CamelCase id。"""
    assert svc.resolve_entity_type("softwareapplication") == "SoftwareApplication"


def test_resolve_entity_type_unknown_value_passes_through_unchanged():
    assert svc.resolve_entity_type("TotallyMadeUpType") == "TotallyMadeUpType"


def test_resolve_entity_type_multi_value_comma_separated():
    assert svc.resolve_entity_type("Person, product") == "PERSON,PRODUCT"


def test_resolve_entity_type_empty_or_blank_passthrough():
    assert svc.resolve_entity_type("") == ""
    assert svc.resolve_entity_type("   ") == "   "


@pytest.mark.asyncio
async def test_extract_svo_triples_normalizes_entity_types_via_two_tier_lookup():
    """subject_type／object_type 選填、可多值、不強制驗證（見 3.1.4），但仍應
    正規化大小寫變體：核心庫優先，查不到才查擴充庫，皆查無對應時保留原值。"""
    llm = FakeLLM("""
    {"triples":[
      {"subject":"A","subject_type":"local business","rel_type":"CAUSES","verb":"導致",
       "object":"B","object_type":"softwareapplication","confidence":4}
    ]}
    """)

    triples = await svc.extract_svo_triples("A 導致 B。", llm)

    assert triples[0].subject_type == "LOCAL_BUSINESS"
    assert triples[0].object_type == "SoftwareApplication"


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
        source="內政部_台內勞字第356410號函.md",
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
    # 2026-08-19：冗餘存下原始文件名稱字串（見 SVOTriple.source docstring）——
    # source_doc_id 是單向雜湊，chunk 檔名在同長度文件間可能撞名，唯有這個
    # 欄位能讓查詢端不必另外查資料庫就回溯到原文。
    assert citations[0]["source"] == "內政部_台內勞字第356410號函.md"
    assert citations[0]["source_svo_chunk_index"] == 2
    assert citations[0]["source_sentence_start"] == 5
    assert citations[0]["source_sentence_end"] == 7
    assert citations[0]["verb"] == "導致"


# ── _fetch_entity_candidates（DEDUP3／DEDUP4 型別集合篩選，見
# docs/報告/11_抽取管線完整實作任務書.md P1-1）：型別選填、可多值，篩選規則
# 為「集合有交集，或查詢/既有節點任一方型別缺席」皆視為候選，只有雙方都有
# 型別且集合無交集才排除——這裡補齊先前只間接透過 resolve_entity_name／
# merge_entity 測試覆蓋、從未直接測過的候選篩選函式本身。─────────────────

@pytest.mark.asyncio
async def test_fetch_entity_candidates_returns_all_when_query_type_empty():
    driver = FakeDriver(records=[
        FakeRecord(name="台積電", type="組織"),
        FakeRecord(name="張忠謀", type="人物"),
    ])

    candidates = await svc._fetch_entity_candidates(driver, uuid4(), "")

    assert {c["name"] for c in candidates} == {"台積電", "張忠謀"}


@pytest.mark.asyncio
async def test_fetch_entity_candidates_excludes_disjoint_type():
    driver = FakeDriver(records=[FakeRecord(name="新竹", type="地點")])

    candidates = await svc._fetch_entity_candidates(driver, uuid4(), "人物")

    assert candidates == []


@pytest.mark.asyncio
async def test_fetch_entity_candidates_includes_exact_name_match_despite_disjoint_type():
    """2026-08-30 修正（真實抽取發現的真實 bug）：即使型別集合無交集，只要
    `name` 與既有節點精確字串相符，仍必須納入候選——否則 `resolve_entity_name()`
    的精確相符短路完全看不到既有正確節點，會退化成用編輯距離/cosine比對到
    錯誤候選，後續改名邏輯撞上既有節點觸發 ConstraintError（真實案例：
    「中央主管機關」有時判成 ORGANIZATION、有時沒有明確型別）。"""
    driver = FakeDriver(records=[FakeRecord(name="中央主管機關", type="ORGANIZATION")])

    candidates = await svc._fetch_entity_candidates(driver, uuid4(), "概念", name="中央主管機關")

    assert {c["name"] for c in candidates} == {"中央主管機關"}


@pytest.mark.asyncio
async def test_fetch_entity_candidates_includes_partial_type_overlap():
    """查詢型別「人物,組織」與既有節點型別「組織,地點」有交集（組織），
    即使非完全相等也應視為候選——完全相等篩選會誤刪本該比對的候選。"""
    driver = FakeDriver(records=[FakeRecord(name="台積電", type="組織,地點")])

    candidates = await svc._fetch_entity_candidates(driver, uuid4(), "人物,組織")

    assert {c["name"] for c in candidates} == {"台積電"}


@pytest.mark.asyncio
async def test_fetch_entity_candidates_includes_candidate_with_missing_type():
    """既有節點型別缺席（None／空字串）時視為不設限，直接納入候選。"""
    driver = FakeDriver(records=[
        FakeRecord(name="無型別實體", type=None),
        FakeRecord(name="空字串型別實體", type=""),
    ])

    candidates = await svc._fetch_entity_candidates(driver, uuid4(), "人物")

    assert {c["name"] for c in candidates} == {"無型別實體", "空字串型別實體"}


@pytest.mark.asyncio
async def test_fetch_entity_candidates_includes_exact_type_match():
    driver = FakeDriver(records=[FakeRecord(name="台積電", type="組織")])

    candidates = await svc._fetch_entity_candidates(driver, uuid4(), "組織")

    assert {c["name"] for c in candidates} == {"台積電"}


@pytest.mark.asyncio
async def test_fetch_entity_candidates_passes_through_persisted_name_embedding():
    """2026-08-03 節點向量化效能改造：已回填的既有節點應原樣帶回
    `name_embedding`，供 `resolve_entity_name` 直接沿用不必重新編碼；尚未
    回填的舊節點（無此屬性）回傳 `None`，兩者混存不影響候選篩選邏輯本身。"""
    driver = FakeDriver(records=[
        FakeRecord(name="台積電", type="組織", name_embedding=[1.0, 0.0]),
        FakeRecord(name="鴻海", type="組織", name_embedding=None),
    ])

    candidates = await svc._fetch_entity_candidates(driver, uuid4(), "組織")

    by_name = {c["name"]: c["name_embedding"] for c in candidates}
    assert by_name["台積電"] == [1.0, 0.0]
    assert by_name["鴻海"] is None


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
async def test_resolve_entity_name_picks_best_edit_ratio_match_not_first():
    """迴歸測試（2026-08-19 真實審查發現並修復）：`_fetch_entity_candidates()`
    的 Cypher 查詢沒有 ORDER BY，Neo4j 回傳順序非決定性；原本的編輯距離比對
    迴圈「回傳第一個超過門檻的候選」，若有多個候選都超過門檻，選到哪一個
    取決於查詢回傳順序，並非最佳匹配。這裡刻意讓分數較低（0.75）的候選排在
    分數較高（≈0.857）的候選之前，驗證修復後會選分數最高者，而非第一個。"""
    candidates = [
        {"name": "台積電公司", "alias_counts_json": "{}"},  # ratio ≈ 0.75，排第一但非最佳
        {"name": "台積電廠", "alias_counts_json": "{}"},      # ratio ≈ 0.857，較佳匹配
    ]
    resolved = await svc.resolve_entity_name("台積電", candidates)
    assert resolved == "台積電廠"


@pytest.mark.asyncio
async def test_resolve_entity_name_edit_ratio_choice_is_order_independent():
    """同一組候選、順序相反，應得到相同結果——模擬 Neo4j 查詢順序不保證的
    情境，確認修復後的合併決策不再受候選回傳順序影響。"""
    candidates_reversed = [
        {"name": "台積電廠", "alias_counts_json": "{}"},
        {"name": "台積電公司", "alias_counts_json": "{}"},
    ]
    resolved = await svc.resolve_entity_name("台積電", candidates_reversed)
    assert resolved == "台積電廠"


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

    async def fake_encode(text: str) -> list[float]:
        angle = 0.6 if text == "Foo Company" else 0.0  # cos(0.6) ≈ 0.825，落在灰色地帶
        return [math.cos(angle), math.sin(angle)] + [0.0] * 6

    async def fake_encode_batch(texts: list[str]) -> list[list[float]]:
        return [await fake_encode(t) for t in texts]

    embedding = FakeEmbedding()
    embedding.encode = fake_encode  # type: ignore[method-assign]
    embedding.encode_batch = fake_encode_batch  # type: ignore[method-assign]

    candidates = [{"name": "XYZ Corp", "alias_counts_json": "{}"}]
    llm = FakeLLM("是")

    resolved = await svc.resolve_entity_name(
        "Foo Company", candidates, embedding_provider=embedding, llm_provider=llm
    )

    assert resolved == "XYZ Corp"
    assert "Foo Company" in llm.prompts[0] and "XYZ Corp" in llm.prompts[0]


@pytest.mark.asyncio
async def test_resolve_entity_name_uses_stored_embedding_without_reencoding_candidate():
    """2026-08-03 節點向量化效能改造：候選已帶 `name_embedding` 時，直接
    沿用比對，不應再對該候選名稱呼叫 `encode()`——判斷結果應與即時編碼完全
    一致（同一 provider、同一段文字，向量數值相同），純粹省去重複編碼。"""
    embedding = FakeEmbedding(similar_to={"I-35": "Interstate Highway 35"})
    encoded_calls: list[str] = []
    original_encode = embedding.encode

    async def tracking_encode(text: str) -> list[float]:
        encoded_calls.append(text)
        return await original_encode(text)

    embedding.encode = tracking_encode  # type: ignore[method-assign]
    stored_vector = await original_encode("Interstate Highway 35")
    candidates = [{"name": "Interstate Highway 35", "name_embedding": stored_vector}]

    resolved = await svc.resolve_entity_name("I-35", candidates, embedding_provider=embedding)

    assert resolved == "Interstate Highway 35"
    assert "Interstate Highway 35" not in encoded_calls  # 候選不應被重新編碼
    assert encoded_calls == ["I-35"]  # 只有查詢名稱本身需要即時編碼


@pytest.mark.asyncio
async def test_resolve_entity_name_falls_back_to_encoding_when_candidate_missing_embedding():
    """候選缺漏 `name_embedding`（舊資料尚未回填）時，行為應退化為即時編碼
    比對——維持改造前的正確性，不因缺漏而漏比對或報錯。"""
    embedding = FakeEmbedding(similar_to={"I-35": "Interstate Highway 35"})
    candidates = [{"name": "Interstate Highway 35", "name_embedding": None}]

    resolved = await svc.resolve_entity_name("I-35", candidates, embedding_provider=embedding)

    assert resolved == "Interstate Highway 35"


@pytest.mark.asyncio
async def test_resolve_entity_name_gray_zone_without_llm_creates_new_entity():
    import math

    async def fake_encode(text: str) -> list[float]:
        angle = 0.6 if text == "Foo Company" else 0.0
        return [math.cos(angle), math.sin(angle)] + [0.0] * 6

    embedding = FakeEmbedding()
    embedding.encode = fake_encode  # type: ignore[method-assign]

    candidates = [{"name": "XYZ Corp", "alias_counts_json": "{}"}]
    resolved = await svc.resolve_entity_name("Foo Company", candidates, embedding_provider=embedding)
    assert resolved == "Foo Company"


# ── _execute_with_constraint_retry（2026-08-30，真實抽取發現 Entity 唯一
# 約束在循序執行下仍可能撞上 ConstraintError，見函式 docstring）──────────


class _FlakyOnceDriver:
    """第一次呼叫 execute_query 拋出 ConstraintError，之後正常回傳——模擬
    MERGE 撞上唯一約束、重試後成功命中既有節點的情境。"""

    def __init__(self):
        self.call_count = 0

    async def execute_query(self, query: str, **params):
        self.call_count += 1
        if self.call_count == 1:
            raise ConstraintError("Node already exists")
        return FakeResult([])


class _AlwaysFailsDriver:
    """每次呼叫都拋出 ConstraintError——驗證重試僅一次，不會無限吞掉例外。"""

    def __init__(self):
        self.call_count = 0

    async def execute_query(self, query: str, **params):
        self.call_count += 1
        raise ConstraintError("Node already exists")


@pytest.mark.asyncio
async def test_execute_with_constraint_retry_succeeds_on_second_attempt():
    driver = _FlakyOnceDriver()

    result = await svc._execute_with_constraint_retry(
        driver, "MERGE (e:Entity) RETURN e", retry_delay_seconds=0, name="x"
    )

    assert result.records == []
    assert driver.call_count == 2  # 第一次撞約束，第二次重試成功


@pytest.mark.asyncio
async def test_execute_with_constraint_retry_reraises_after_max_attempts():
    """最多重試到 max_attempts 次——若一直失敗，代表是別的問題，不可無限
    重試吞掉例外。"""
    driver = _AlwaysFailsDriver()

    with pytest.raises(ConstraintError):
        await svc._execute_with_constraint_retry(
            driver, "MERGE (e:Entity) RETURN e", max_attempts=3, retry_delay_seconds=0, name="x"
        )

    assert driver.call_count == 3  # 原始呼叫 + 兩次重試，不會有第四次


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
async def test_merge_entity_persists_name_embedding_on_new_node():
    """2026-08-03 節點向量化效能改造：`embedding_provider` 提供時，新建節點
    的 `ON CREATE` 應順便存 `name_embedding`，供未來比對直接沿用。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding()

    await svc.merge_entity(
        driver, kg_id, "台積電", "組織", "台積電",
        source_doc_id=uuid4(), source_svo_chunk_index=1,
        embedding_provider=embedding,
    )

    assert driver.entities[(str(kg_id), "台積電")]["name_embedding"] == await embedding.encode("台積電")


@pytest.mark.asyncio
async def test_merge_entity_without_chunk_info_also_persists_name_embedding():
    """未提供 chunk 追溯資訊的退化路徑（純 MERGE 節點）同樣應存 `name_embedding`，
    兩條建立節點的路徑行為一致，不留下其中一條沒有 embedding 的缺口。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding()

    await svc.merge_entity(driver, kg_id, "泰國", "LOCATION", "泰國", embedding_provider=embedding)

    assert driver.entities[(str(kg_id), "泰國")]["name_embedding"] == await embedding.encode("泰國")


@pytest.mark.asyncio
async def test_merge_entity_does_not_overwrite_embedding_of_existing_node():
    """既有節點（`MERGE` 命中、非新建）不應被覆寫 `name_embedding`——
    `ON CREATE SET` 語意本就只在建立當下生效，這裡驗證改造沒有意外破壞
    既有節點的資料。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding()
    doc_id = uuid4()

    await svc.merge_entity(
        driver, kg_id, "台積電", "組織", "台積電",
        source_doc_id=doc_id, source_svo_chunk_index=1, embedding_provider=embedding,
    )
    original_vector = driver.entities[(str(kg_id), "台積電")]["name_embedding"]

    await svc.merge_entity(
        driver, kg_id, "台積電", "組織", "台積電",
        source_doc_id=doc_id, source_svo_chunk_index=2, embedding_provider=embedding,
    )

    assert driver.entities[(str(kg_id), "台積電")]["name_embedding"] == original_vector


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
async def test_merge_entity_falls_back_to_resolved_name_when_promotion_collides(monkeypatch):
    """2026-08-30 真實抽取發現的真實 bug：跨文件標準名提升（RECHECK）決定把
    `resolved_name` 改名成 `final_name`（更常見的別名）時，`final_name` 可能
    已經是另一個既有節點的名稱（見 `_fetch_entity_candidates()` docstring
    的根因說明），此時 `SET e.name = $final_name` 撞上唯一約束。這是決定性
    的名稱衝突、不是可重試解決的競態——不應讓整個 chunk 抽取失敗，應保留
    `resolved_name`（已成功 MERGE 的既有節點）不改名。"""
    kg_id = uuid4()

    class _RenameCollisionDriver:
        def __init__(self):
            self.rename_attempts = 0

        async def execute_query(self, query, **params):
            if query.startswith("MATCH (e:Entity {kg_id: $kg_id, name: $resolved_name}) SET e.name"):
                self.rename_attempts += 1
                raise ConstraintError("Node already exists")
            return FakeResult([])

    driver = _RenameCollisionDriver()

    async def fake_fetch_candidates(*a, **k):
        return []

    async def fake_resolve_entity_name(*a, **k):
        return "中央主管機關備查"  # 模擬型別篩選漏掉精確相符、比對到錯誤候選

    async def fake_merge_chunk_mention(*a, **k):
        return None

    async def fake_aggregate_alias_counts(*a, **k):
        return {"中央主管機關備查": 1, "中央主管機關": 5}

    monkeypatch.setattr(svc, "_fetch_entity_candidates", fake_fetch_candidates)
    monkeypatch.setattr(svc, "resolve_entity_name", fake_resolve_entity_name)
    monkeypatch.setattr(svc, "_merge_chunk_mention", fake_merge_chunk_mention)
    monkeypatch.setattr(svc, "_aggregate_alias_counts", fake_aggregate_alias_counts)
    monkeypatch.setattr(svc, "should_promote_by_frequency", lambda *a, **k: True)

    final_name = await svc.merge_entity(
        driver, kg_id, "中央主管機關", "概念", "中央主管機關",
        source_doc_id=uuid4(), source_svo_chunk_index=1,
    )

    assert final_name == "中央主管機關備查"  # 改名失敗，保留原本已成功命中的名稱
    assert driver.rename_attempts == 1  # 只嘗試一次改名，不會無限重試（決定性衝突重試無意義）


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
        subject="台積電", rel_type="CAUSES", verb="生產", object="晶片",
        source_doc_id=doc_id, source_svo_chunk_index=1,
    )
    second = SVOTriple(
        subject="台積電公司", rel_type="CAUSES", verb="生產", object="晶片",
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
    expected_doc_id = str(document_record_service.document_uuid("note.md"))
    for (query, params), chunk in zip(driver.calls, chunks):
        assert "c.embedding" in query
        assert params["kg_id"] == str(kg_id)
        assert params["source_doc_id"] == expected_doc_id  # 2026-08-18：與 _merge_chunk_mention() 共用同一把 MERGE 鍵
        assert params["source"] == "note.md"  # 仍保留為一般屬性，供除錯／回溯
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
            "source": "內政部_台內勞字第356410號函.md",
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
    # 2026-08-19：source 欄位也要正確從 citation 還原回來，不是只有
    # source_doc_id——見 SVOTriple.source docstring 的回溯可靠性說明。
    assert triples[0].source == "內政部_台內勞字第356410號函.md"
    assert triples[0].source_sentence_start == 1
    assert triples[0].verb == "導致"


@pytest.mark.asyncio
async def test_bfs_query_restricts_traversal_to_svo_rel_types():
    """2026-08-19 迴歸測試：走訪必須限定在 SVO_REL_TYPES（知識層邊），不能
    是不限型別的 `[*1..{hops}]`——否則圖上同時存在 § 3.1.4 §a 的
    HAS_ENTITY／HAS_SUBJECT／HAS_OBJECT／SUPPORTED_BY 結構性邊時，BFS 可能
    行經這些邊、把 startNode/endNode 解析成沒有 `.name` 的 Chunk／Fact
    節點，導致 `SVOTriple(subject=None)` 驗證失敗直接拋例外（真實對新建立
    的 3.1.4 驗證 KG 執行時重現過一次，見 docs/報告/15_...md）。"""
    driver = FakeDriver(records=[])

    await svc.bfs_query(driver, uuid4(), ["A"], hops=2)

    assert len(driver.calls) == 1
    query, _params = driver.calls[0]
    assert "[*1..2]" not in query  # 不應該再出現不限關係型別的走訪模式
    assert "HAS_ENTITY" not in query
    for rel_type in SVO_REL_TYPES:
        assert rel_type in query


# ── trigger_extraction（原 routers/staging.py::_trigger_extraction，遷移自
# tests/routers/test_staging.py，見 docs/報告/11_抽取管線完整實作任務書.md P0-2）──

@pytest.mark.asyncio
async def test_trigger_extraction_enqueues_produced_chunks(tmp_path, monkeypatch):
    """對應 § 3.1.2「立即觸發抽取任務」：文件搬進 KG 資料夾後，
    CHUNKREADY 產出的 SVO chunk 應被登記進 task_queue.db。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage("單句無代名詞。", "note.md", kg_folder)

    kg_id = uuid4()
    await svc.trigger_extraction(FakeDriver(), doc_folder, kg_id)

    pending = task_queue_service.next_pending(config.task_queue_db_path(), str(kg_id))
    assert pending == (str(kg_id), "note.md", 1)


@pytest.mark.asyncio
async def test_trigger_extraction_records_svo_chunk_total(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage("第一句話。" * 100, "big.txt", kg_folder)

    await svc.trigger_extraction(FakeDriver(), doc_folder, uuid4())

    updated = document_record_service.read_record(doc_folder)
    assert updated.svo_total_chunks > 0


@pytest.mark.asyncio
async def test_trigger_extraction_uses_article_aware_chunking_when_articles_given(tmp_path, monkeypatch):
    """`articles` 提供時原樣轉交 `prepare_svo_ready_chunks()`（見 § 3.5「實作
    範圍定案」），排隊的 chunk 數應對應通過濾除規則後的條文數，而非 `staging`
    階段暫存的無關文字。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    # staging 階段的文字與法條無關，用來驗證 articles 路徑確實略過既有句子清單。
    doc_folder, _record = ingestion_service.chunk_and_stage("佔位文字。", "N0030001_勞動基準法", kg_folder)

    articles = [
        {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "第一章 總則"},
        {"ArticleType": "A", "ArticleNo": "第 1 條", "ArticleContent": "本法保障其權益。"},
        {"ArticleType": "A", "ArticleNo": "第 2 條", "ArticleContent": "本法定義如下。"},
    ]
    kg_id = uuid4()
    await svc.trigger_extraction(FakeDriver(), doc_folder, kg_id, articles=articles)

    pending = task_queue_service.next_pending(config.task_queue_db_path(), str(kg_id))
    assert pending == (str(kg_id), "N0030001_勞動基準法", 1)

    updated = document_record_service.read_record(doc_folder)
    assert updated.svo_total_chunks == 2  # 章節標題（ArticleNo 為空）被濾除


@pytest.mark.asyncio
async def test_trigger_extraction_is_noop_when_record_missing(tmp_path, monkeypatch):
    """資料夾沒有記錄檔（異常狀態）時不應拋出例外，只是靜默跳過。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    empty_folder = tmp_path / "no-record"
    empty_folder.mkdir()

    await svc.trigger_extraction(FakeDriver(), empty_folder, uuid4())  # 不應拋出例外


@pytest.mark.asyncio
async def test_trigger_extraction_skips_embedding_when_provider_not_initialized(tmp_path, monkeypatch):
    """對應誠實侷限：測試環境未呼叫 `init_providers()`，`get_embedding_provider()`
    會拋出 RuntimeError，應優雅跳過向量化，不影響切塊與排隊本身。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage("單句無代名詞。", "note.md", kg_folder)

    await svc.trigger_extraction(FakeDriver(), doc_folder, uuid4())  # 不應拋出例外

    pending = task_queue_service.next_pending(config.task_queue_db_path())
    assert pending is not None


@pytest.mark.asyncio
async def test_trigger_extraction_embeds_chunks_when_provider_available(tmp_path, monkeypatch):
    """對應 2026-07-22 使用者確認：切塊當下順便向量化，供未來來源篩選使用。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "馬斯克創立了太空公司。他隨後研發了獵鷹火箭。", "note.md", kg_folder,
    )

    call_count = {"n": 0}

    class FakeEmbedding:
        dim = 4
        model_name = "fake-embedding"

        async def encode(self, text: str) -> list[float]:
            return [0.0] * self.dim

        async def encode_batch(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * self.dim for _ in texts]

    def _get_fake_embedding_provider():
        call_count["n"] += 1
        return FakeEmbedding()

    fake_driver = FakeDriver()
    monkeypatch.setattr("services.svo_service.get_embedding_provider", _get_fake_embedding_provider)

    await svc.trigger_extraction(fake_driver, doc_folder, uuid4())

    embed_calls = [c for c in fake_driver.calls if "c.embedding" in c[0]]
    assert len(embed_calls) >= 1
    # SENTEMBED（prepare_svo_ready_chunks 內部）也應該收到同一個 provider 實例，
    # 而非各自重新 fetch 一次
    assert call_count["n"] == 1
    from services.svo_preprocessing_service import read_sentence_embeddings
    assert read_sentence_embeddings("note.md", kg_folder) is not None

    # 2026-08-20 § Phase 1：同一次 trigger_extraction() 呼叫應一併建立
    # Sentence 節點（供標準化 RAG 檢索），非獨立另外觸發的路徑。
    sentence_calls = [c for c in fake_driver.calls if "s.sentence_embedding" in c[0]]
    assert len(sentence_calls) >= 1


@pytest.mark.asyncio
async def test_trigger_extraction_skips_pronoun_resolution_when_llm_not_initialized(tmp_path, monkeypatch):
    """對應誠實侷限：測試環境未呼叫 `init_providers()`，`get_llm_provider()`
    會拋出 RuntimeError，指代消解應優雅退化為原句直接通過，不影響切塊與排隊
    本身——與既有 embedding provider 的降級行為對稱。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "馬斯克創立了太空公司。他隨後研發了獵鷹火箭。", "note.md", kg_folder,
    )

    await svc.trigger_extraction(FakeDriver(), doc_folder, uuid4())  # 不應拋出例外

    chunk_files = sorted(doc_folder.glob("svo-chunk-*.md"))
    assert chunk_files
    assert "他隨後研發了獵鷹火箭" in chunk_files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_trigger_extraction_resolves_pronouns_when_llm_available(tmp_path, monkeypatch):
    """2026-08-20：對應 docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md
    §0 前提缺口修復——`trigger_extraction()` 帶入 `pronoun_llm_provider` 後，
    SVO chunk 的實際文字（`build_svo_chunks()` 的 `chunk.text`，也就是送進
    `LLM_SVO` 三元組抽取的原文）應反映指代消解後的結果，而非原句代名詞。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "馬斯克創立了太空公司。他隨後研發了獵鷹火箭。", "note.md", kg_folder,
    )

    call_count = {"n": 0}

    class FakeLLM:
        def __init__(self):
            self.responses = ["馬斯克隨後研發了獵鷹火箭。"]

        async def generate(self, prompt: str) -> str:
            return self.responses.pop(0)

    def _get_fake_llm_provider():
        call_count["n"] += 1
        return FakeLLM()

    monkeypatch.setattr("services.svo_service.get_llm_provider", _get_fake_llm_provider)

    await svc.trigger_extraction(FakeDriver(), doc_folder, uuid4())

    assert call_count["n"] == 1  # 只從 trigger_extraction() fetch 一次，非各自重複 fetch
    chunk_files = sorted(doc_folder.glob("svo-chunk-*.md"))
    assert chunk_files
    chunk_text = chunk_files[0].read_text(encoding="utf-8")
    assert "馬斯克隨後研發了獵鷹火箭" in chunk_text
    assert "他隨後研發了獵鷹火箭" not in chunk_text


class KGLexiconFakeDriver:
    """模擬 `KGRepository.get()` 查詢會回傳指定 `pronoun_lexicon_exclude` 的
    `KnowledgeGraph` 節點，其餘查詢一律回傳空結果並記錄——供
    `trigger_extraction()` 讀取 KG 專屬代名詞排除詞庫的測試使用（2026-08-20，
    見 `services/svo_service.py::trigger_extraction()` docstring「KG 專屬
    代名詞排除詞庫」小節）。"""

    def __init__(self, kg_id, pronoun_lexicon_exclude: list[str]):
        self._kg_id = kg_id
        self._pronoun_lexicon_exclude = pronoun_lexicon_exclude
        self.calls: list = []

    async def execute_query(self, query: str, **params):
        self.calls.append((query, params))
        if "MATCH (k:KnowledgeGraph" in query:
            now = "2026-08-20T00:00:00+00:00"
            node = {
                "id": str(self._kg_id), "name": "test-kg", "description": "",
                "folder_path": "/tmp/x", "is_public": True, "db_name": "",
                "doc_count": 0, "entity_count": 0, "relation_count": 0,
                "pronoun_lexicon_exclude": self._pronoun_lexicon_exclude,
                "created_at": now, "updated_at": now,
            }
            return FakeResult([{"k": node}])
        return FakeResult([])


@pytest.mark.asyncio
async def test_trigger_extraction_excludes_kg_specific_pronoun_words(tmp_path, monkeypatch):
    """2026-08-20：真實匯入法規全文資料集時發現，「其」「該」在法律文本中
    幾乎都是自我完備的正式泛稱（如「及其家屬」「該法」），`DEFAULT_PRONOUN_LEXICON`
    的字面比對規則卻一律當成代名詞觸發 LLM 消解——實測某份 390 句的法規全文
    41% 的句子因此觸發，單筆文件耗時超過 600 秒。KG 節點的
    `pronoun_lexicon_exclude` 讓個別 KG 排除這些字；本測試驗證
    `trigger_extraction()` 真的把該欄位套用到消解管線本身（讓 LLM 完全不被
    呼叫），不是只加了欄位卻沒接上。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "本法保障其權益。", "note.md", kg_folder,
    )

    class ExplodingLLM:
        async def generate(self, prompt: str) -> str:
            raise AssertionError("「其」已被 KG 排除詞庫排除，不應觸發 LLM 消解")

    monkeypatch.setattr("services.svo_service.get_llm_provider", lambda: ExplodingLLM())

    kg_id = uuid4()
    driver = KGLexiconFakeDriver(kg_id, pronoun_lexicon_exclude=["其", "該"])

    await svc.trigger_extraction(driver, doc_folder, kg_id)  # 不應拋出例外（LLM 未被呼叫）

    chunk_files = sorted(doc_folder.glob("svo-chunk-*.md"))
    assert chunk_files
    assert "本法保障其權益" in chunk_files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_trigger_extraction_resolves_excluded_word_when_kg_has_no_override(tmp_path, monkeypatch):
    """對照組：KG 沒有設定 `pronoun_lexicon_exclude`（`KGLexiconFakeDriver`
    回傳空清單）時，「其」仍應維持在預設詞庫內、正常觸發消解——確認排除
    行為只影響明確設定過的 KG，不是全域改動預設詞庫本身。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))

    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_folder, _record = ingestion_service.chunk_and_stage(
        "本法保障其權益。", "note.md", kg_folder,
    )

    class FakeLLM:
        async def generate(self, prompt: str) -> str:
            return "本法保障勞工權益。"

    monkeypatch.setattr("services.svo_service.get_llm_provider", lambda: FakeLLM())

    kg_id = uuid4()
    driver = KGLexiconFakeDriver(kg_id, pronoun_lexicon_exclude=[])

    await svc.trigger_extraction(driver, doc_folder, kg_id)

    chunk_files = sorted(doc_folder.glob("svo-chunk-*.md"))
    assert chunk_files
    assert "本法保障勞工權益" in chunk_files[0].read_text(encoding="utf-8")


# ── 3.1.4 §a：事實層級向量化（Fact 節點，2026-08-03）────────────────────────

def test_verbalize_fact_includes_types_when_present():
    text = svc._verbalize_fact("台積電", "組織", "生產", "晶片", "產品")
    assert text == "台積電（組織） 生產 晶片（產品）"


def test_verbalize_fact_omits_parens_when_type_missing():
    """型別選填，缺席時不留空括號。"""
    text = svc._verbalize_fact("A", "", "導致", "B", "")
    assert text == "A 導致 B"


@pytest.mark.asyncio
async def test_merge_triples_to_graph_creates_fact_node_with_embedding_when_provider_given():
    """3.1.4 §a：`embedding_provider` 提供且有 chunk 追溯資訊時，應為這筆
    citation 建立一個 Fact 節點，`fact_text` 用 verbalize 後的三元組文字，
    連結 subject/object/chunk。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    doc_id = uuid4()
    embedding = FakeEmbedding()
    triple = SVOTriple(
        subject="台積電", subject_type="組織", rel_type="CAUSES", verb="生產",
        object="晶片", object_type="產品",
        source_doc_id=doc_id, source_svo_chunk_index=1,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [triple], embedding_provider=embedding)

    assert len(driver.facts) == 1
    fact = driver.facts[0]
    assert fact["kg_id"] == str(kg_id)
    assert fact["subject"] == "台積電"
    assert fact["object"] == "晶片"
    assert fact["rel_type"] == "CAUSES"  # 2026-08-18 追加：§b 回填批次任務的冪等比對鍵需要
    assert fact["verb"] == "生產"
    assert fact["confidence"] == 1
    assert fact["source_doc_id"] == str(doc_id)
    assert fact["chunk_index"] == 1
    expected_text = svc._verbalize_fact("台積電", "組織", "生產", "晶片", "產品")
    assert fact["fact_text"] == expected_text
    assert fact["fact_embedding"] == await embedding.encode(expected_text)


@pytest.mark.asyncio
async def test_merge_triples_to_graph_threads_article_no_into_fact_node():
    """2026-08-24（見 03 §3.5「實作範圍定案」下一步）：`SVOTriple.source_article_no`
    有值時（`ArticleAwareChunking` 產生的 chunk），應原樣傳入 `_create_fact_node()`
    的 `article_no` 參數，供其 `SUPPORTED_BY` 改連向 `LawArticle`。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    doc_id = uuid4()
    embedding = FakeEmbedding()
    triple = SVOTriple(
        subject="雇主", rel_type="OBLIGATED_TO", verb="應供應", object="飲用水",
        source_doc_id=doc_id, source_svo_chunk_index=5, source_article_no="第 5 條",
    )

    await svc.merge_triples_to_graph(driver, kg_id, [triple], embedding_provider=embedding)

    assert len(driver.facts) == 1
    assert driver.facts[0]["article_no"] == "第 5 條"


@pytest.mark.asyncio
async def test_merge_triples_to_graph_passes_none_article_no_for_ordinary_documents():
    """`source_article_no` 未設定（一般文件，`SVOGROUP` 產生的 chunk）時應為
    `None`，確認新參數不影響既有一般文件的行為。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding()
    triple = SVOTriple(
        subject="台積電", subject_type="組織", rel_type="CAUSES", verb="生產",
        object="晶片", object_type="產品",
        source_doc_id=uuid4(), source_svo_chunk_index=1,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [triple], embedding_provider=embedding)

    assert driver.facts[0]["article_no"] is None


@pytest.mark.asyncio
async def test_create_fact_node_matches_law_article_when_article_no_given():
    """`_create_fact_node()` 直接單元測試：`article_no` 提供時，`SUPPORTED_BY`
    連結目標的 `MATCH` 應改為 `LawArticle`，不再是 `Chunk`。"""
    driver = FakeDriver(records=[{"f": {}}])
    kg_id = uuid4()

    created = await svc._create_fact_node(
        driver, str(kg_id),
        subject="雇主", object_="飲用水", rel_type="OBLIGATED_TO",
        source_doc_id=str(uuid4()), chunk_index=5,
        fact_text="雇主 應供應 飲用水", fact_embedding=[0.1],
        verb="應供應", confidence=1, article_no="第 5 條",
    )

    assert created is True
    query, params = driver.calls[0]
    assert "MATCH (c:LawArticle {kg_id: $kg_id, source_doc_id: $source_doc_id, article_no: $article_no})" in query
    assert "MATCH (c:Chunk" not in query
    assert params["article_no"] == "第 5 條"


@pytest.mark.asyncio
async def test_create_fact_node_matches_chunk_when_article_no_absent():
    """`article_no` 未提供（`None`，預設）時，行為與新增此參數前完全一致——
    仍 `MATCH (c:Chunk ...)`，不觸及 `LawArticle`。"""
    driver = FakeDriver(records=[{"f": {}}])
    kg_id = uuid4()

    await svc._create_fact_node(
        driver, str(kg_id),
        subject="台積電", object_="晶片", rel_type="CAUSES",
        source_doc_id=str(uuid4()), chunk_index=1,
        fact_text="台積電 生產 晶片", fact_embedding=[0.1],
        verb="生產", confidence=1,
    )

    query, params = driver.calls[0]
    assert "MATCH (c:Chunk {kg_id: $kg_id, source_doc_id: $source_doc_id, chunk_index: $chunk_index})" in query
    assert "LawArticle" not in query
    assert params["article_no"] is None


@pytest.mark.asyncio
async def test_merge_triples_to_graph_skips_fact_creation_without_embedding_provider():
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    triple = SVOTriple(
        subject="A", rel_type="CAUSES", verb="導致", object="B",
        source_doc_id=uuid4(), source_svo_chunk_index=1,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [triple])

    assert driver.facts == []


@pytest.mark.asyncio
async def test_merge_triples_to_graph_skips_fact_creation_without_chunk_info():
    """缺少 `source_doc_id`／`source_svo_chunk_index` 時無法連結 `SUPPORTED_BY`
    對應的 `Chunk` 節點（`merge_entity` 也不會建立該 Chunk），應跳過，不建立
    不完整的 Fact 節點。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding()
    triple = SVOTriple(subject="A", rel_type="CAUSES", verb="導致", object="B")

    await svc.merge_triples_to_graph(driver, kg_id, [triple], embedding_provider=embedding)

    assert driver.facts == []


@pytest.mark.asyncio
async def test_merge_triples_to_graph_creates_separate_fact_per_citation_even_when_edge_collapses():
    """對應 3.1.4 §a『Fact 節點一律以每筆 citation 為粒度，永不相互覆蓋或
    平均』——即使兩筆抽取收斂成同一條 MERGE 邊（同一 (subject, rel_type,
    object)，見既有事實層級去重行為），仍應各自產生獨立的 Fact 節點。"""
    driver = InMemoryEntityDriver()
    kg_id = uuid4()
    embedding = FakeEmbedding()

    first = SVOTriple(
        subject="馬斯克", rel_type="CREATED_BY", verb="創立", object="SpaceX",
        source_doc_id=uuid4(), source_svo_chunk_index=3,
    )
    second = SVOTriple(
        subject="馬斯克", rel_type="CREATED_BY", verb="創辦", object="SpaceX",
        source_doc_id=uuid4(), source_svo_chunk_index=50,
    )

    await svc.merge_triples_to_graph(driver, kg_id, [first, second], embedding_provider=embedding)

    assert len(driver.relationships) == 1  # 邊仍收斂成一條（既有行為不變）
    assert len(driver.facts) == 2  # Fact 節點各自獨立，不相互覆蓋
    assert {f["verb"] for f in driver.facts} == {"創立", "創辦"}


# ── revoke_chunk_facts（2026-08-28，重抽取前清理，見 docs/論文/03_變更紀錄.md
# 「規則7/8/9 修正前抽取資料的重抽取」設計）──────────────────────────


class _FakeRevokeDriver:
    """辨識 `revoke_chunk_facts()` 實際發出的三種查詢形狀（Fact 刪除計數、
    候選邊列舉、邊更新／刪除），不連線真實 Neo4j 即可驗證 citation 層級的
    精準移除邏輯。"""

    def __init__(self, *, fact_deleted_count: int, edges: list[dict]):
        self.fact_deleted_count = fact_deleted_count
        self._edges = edges  # [{"rel_id": ..., "citations_json": ...}]
        self.set_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    async def execute_query(self, query: str, **params):
        q = query.strip()
        if "MATCH (f:Fact" in q and "DETACH DELETE f" in q:
            return FakeResult([FakeRecord(deleted=self.fact_deleted_count)])
        if q.startswith("MATCH (s:Entity {kg_id: $kg_id})-[r]->(o:Entity"):
            return FakeResult([FakeRecord(**e) for e in self._edges])
        if "SET r.citations_json" in q:
            self.set_calls.append(params)
            return FakeResult([])
        if q.startswith("MATCH ()-[r]->() WHERE elementId(r) = $rel_id DELETE r"):
            self.delete_calls.append(params)
            return FakeResult([])
        raise AssertionError(f"未預期的查詢：{q}")


@pytest.mark.asyncio
async def test_revoke_chunk_facts_reports_fact_deletion_count():
    driver = _FakeRevokeDriver(fact_deleted_count=3, edges=[])

    result = await svc.revoke_chunk_facts(driver, uuid4(), "doc-1", 2)

    assert result["facts_deleted"] == 3
    assert result["edges_updated"] == 0
    assert result["edges_deleted"] == 0


@pytest.mark.asyncio
async def test_revoke_chunk_facts_deletes_edge_when_last_citation_removed():
    """邊上唯一的 citation 就是這個 chunk 的──移除後清單變空，整條邊應該
    被刪除，而不是留下一個 citations_json='[]' 的空殼邊。"""
    citations = json.dumps([
        {"source_doc_id": "doc-1", "source_svo_chunk_index": 2, "confidence": 4},
    ])
    driver = _FakeRevokeDriver(
        fact_deleted_count=0,
        edges=[{"rel_id": "rel-1", "citations_json": citations}],
    )

    result = await svc.revoke_chunk_facts(driver, uuid4(), "doc-1", 2)

    assert result["edges_deleted"] == 1
    assert result["edges_updated"] == 0
    assert driver.delete_calls == [{"rel_id": "rel-1"}]
    assert driver.set_calls == []


@pytest.mark.asyncio
async def test_revoke_chunk_facts_keeps_edge_and_removes_only_matching_citation():
    """邊上還累積了其他 chunk 的 citation（跨 chunk 收斂的既有事實層級去重
    行為）──不能整條邊刪除，只能精準移除屬於這個 chunk 的那一筆，並重算
    confidence（沿用 merge_triples_to_graph() 的 max(citations) 規則）。"""
    citations = json.dumps([
        {"source_doc_id": "doc-1", "source_svo_chunk_index": 2, "confidence": 5},
        {"source_doc_id": "doc-1", "source_svo_chunk_index": 99, "confidence": 2},
    ])
    driver = _FakeRevokeDriver(
        fact_deleted_count=1,
        edges=[{"rel_id": "rel-1", "citations_json": citations}],
    )

    result = await svc.revoke_chunk_facts(driver, uuid4(), "doc-1", 2)

    assert result["edges_updated"] == 1
    assert result["edges_deleted"] == 0
    assert driver.delete_calls == []
    assert len(driver.set_calls) == 1
    remaining = json.loads(driver.set_calls[0]["citations_json"])
    assert len(remaining) == 1
    assert remaining[0]["source_svo_chunk_index"] == 99
    assert driver.set_calls[0]["confidence"] == 2  # 只剩下 chunk 99 的 citation


@pytest.mark.asyncio
async def test_revoke_chunk_facts_ignores_edges_without_matching_citation():
    """邊上的 citation 全部屬於其他 chunk──不應該被動到（既不更新也不
    刪除），避免誤傷跟這次重抽取無關的資料。"""
    citations = json.dumps([
        {"source_doc_id": "doc-1", "source_svo_chunk_index": 99, "confidence": 2},
    ])
    driver = _FakeRevokeDriver(
        fact_deleted_count=0,
        edges=[{"rel_id": "rel-1", "citations_json": citations}],
    )

    result = await svc.revoke_chunk_facts(driver, uuid4(), "doc-1", 2)

    assert result == {"facts_deleted": 0, "edges_updated": 0, "edges_deleted": 0}
    assert driver.set_calls == []
    assert driver.delete_calls == []


@pytest.mark.asyncio
async def test_create_fact_vector_index_without_driver_is_noop():
    await svc.create_fact_vector_index(None)  # 不應拋出例外


@pytest.mark.asyncio
async def test_create_fact_vector_index_without_kg_id_is_noop():
    driver = FakeDriver()
    await svc.create_fact_vector_index(driver)  # kg_id 缺席同樣視為 noop
    assert driver.calls == []


@pytest.mark.asyncio
async def test_create_fact_vector_index_issues_per_kg_create_vector_index_query():
    """2026-08-19：改為每個 KG 各自一個獨立索引（label 與索引名稱皆含
    kg_id），取代原本全 KG 共用單一索引＋查詢後 kg_id 過濾的設計，見
    create_fact_vector_index() docstring 完整查證脈絡。"""
    driver = FakeDriver()
    kg_id = uuid4()

    await svc.create_fact_vector_index(driver, kg_id, dim=384)

    assert len(driver.calls) == 1
    query, params = driver.calls[0]
    assert svc._fact_vector_index_name(str(kg_id)) in query
    assert f"FOR (f:{svc._kg_fact_label(str(kg_id))}) ON f.fact_embedding" in query
    assert params["dim"] == 384


@pytest.mark.asyncio
async def test_vector_search_facts_queries_per_kg_index_without_post_filter():
    """2026-08-19：KG 範圍隔離改由 per-KG 索引結構保證，查詢不再需要
    `WHERE node.kg_id = $kg_id` 這個查詢後 post-filter。"""
    driver = FakeDriver(records=[
        {"fact_text": "台積電 生產 晶片", "verb": "生產", "confidence": 3,
         "subject": "台積電", "object": "晶片", "rel_type": "CAUSES",
         "source_doc_id": "doc-1", "source_svo_chunk_index": 1, "score": 0.92},
    ])
    kg_id = uuid4()

    results = await svc.vector_search_facts(driver, kg_id, [0.1, 0.2], top_k=5)

    assert results == [
        {"fact_text": "台積電 生產 晶片", "verb": "生產", "confidence": 3,
         "subject": "台積電", "object": "晶片", "rel_type": "CAUSES",
         "source_doc_id": "doc-1", "source_svo_chunk_index": 1, "score": 0.92},
    ]
    # 第一次呼叫是 create_fact_vector_index() 的惰性索引建立
    index_query, index_params = driver.calls[0]
    assert svc._fact_vector_index_name(str(kg_id)) in index_query
    assert index_params["dim"] == 2  # 由 query_vector 長度推得，不需額外參數
    # 第二次才是實際的 KNN 查詢
    query, params = driver.calls[1]
    assert svc._fact_vector_index_name(str(kg_id)) in query
    assert "WHERE node.kg_id" not in query
    assert "node.subject AS subject" in query
    assert "node.rel_type AS rel_type" in query
    # 候選池倍數仍保留，供下方去重測試消耗（與 KG 範圍過濾是獨立問題）
    assert params["candidate_k"] == 5 * FACT_SEARCH_CANDIDATE_MULTIPLIER
    assert params["vector"] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_vector_search_entities_scopes_to_kg_before_ranking():
    """2026-08-25 v2（見 docs/報告/17）：v1 的全域共用索引＋候選池
    post-filter 在真實測試中被證實無效（開發用 Neo4j 累積多 KG 時，候選池
    幾乎不含目標 KG 的實體）。v2 改為 `MATCH (e:Entity {kg_id})` 先精確
    過濾到本 KG，再用 `vector.similarity.cosine()` 現算排序，不再依賴
    Neo4j 原生向量索引。"""
    driver = FakeDriver(records=[{"name": "勞工", "score": 0.91}])
    kg_id = uuid4()

    results = await svc.vector_search_entities(driver, kg_id, [0.1, 0.2], top_k=5)

    assert results == ["勞工"]
    query, params = driver.calls[0]
    assert "MATCH (e:Entity {kg_id: $kg_id})" in query
    assert "vector.similarity.cosine" in query
    assert params["kg_id"] == str(kg_id)
    assert params["vector"] == [0.1, 0.2]
    assert params["top_k"] == 5


@pytest.mark.asyncio
async def test_vector_search_entities_filters_out_null_names():
    driver = FakeDriver(records=[{"name": None, "score": 0.9}, {"name": "雇主", "score": 0.8}])

    results = await svc.vector_search_entities(driver, uuid4(), [0.1], top_k=5)

    assert results == ["雇主"]


@pytest.mark.asyncio
async def test_vector_search_facts_dedupes_same_subject_rel_object_keeping_highest_score():
    """同一件事實因多筆 citation（例如切塊重疊）各自產生獨立 Fact 節點時，
    只保留分數最高的一筆，不讓 top_k 名額被近乎重複的結果佔掉——真實資料
    驗證發現（見 docs/報告/15_314修復效果驗證報告_2026-08-19.md），非臆測。"""
    driver = FakeDriver(records=[
        {"fact_text": "生理假不併入普通傷病假（版本一）", "verb": "不併入", "confidence": 3,
         "subject": "生理假", "object": "普通傷病假", "rel_type": "RELATED_TO",
         "source_doc_id": "doc-1", "source_svo_chunk_index": 1, "score": 0.862},
        {"fact_text": "生理假不併入普通傷病假（版本二，分數較高）", "verb": "不併入", "confidence": 3,
         "subject": "生理假", "object": "普通傷病假", "rel_type": "RELATED_TO",
         "source_doc_id": "doc-1", "source_svo_chunk_index": 2, "score": 0.911},
        {"fact_text": "生理假工資折半", "verb": "折半", "confidence": 3,
         "subject": "生理假期間工資", "object": "全勤", "rel_type": "RELATED_TO",
         "source_doc_id": "doc-1", "source_svo_chunk_index": 3, "score": 0.844},
    ])
    kg_id = uuid4()

    results = await svc.vector_search_facts(driver, kg_id, [0.1, 0.2], top_k=5)

    assert len(results) == 2  # 兩筆重複的「生理假不併入普通傷病假」收斂成一筆
    assert results[0]["fact_text"] == "生理假不併入普通傷病假（版本二，分數較高）"
    assert results[0]["score"] == 0.911
    assert results[1]["fact_text"] == "生理假工資折半"


@pytest.mark.asyncio
async def test_vector_search_facts_keeps_entries_with_missing_key_fields_undeduped():
    """subject／rel_type／object 任一為 None（2026-08-18 schema 修正前建立、
    尚未跑過 §b 回填批次的舊 Fact 節點）時無法安全去重，一律原樣保留——與
    routers/agent.py::_merge_fact_lines() 既有的同名情境處理原則一致。"""
    driver = FakeDriver(records=[
        {"fact_text": "舊資料事實一", "verb": None, "confidence": 1,
         "subject": None, "object": None, "rel_type": None,
         "source_doc_id": None, "source_svo_chunk_index": None, "score": 0.80},
        {"fact_text": "舊資料事實二", "verb": None, "confidence": 1,
         "subject": None, "object": None, "rel_type": None,
         "source_doc_id": None, "source_svo_chunk_index": None, "score": 0.79},
    ])
    kg_id = uuid4()

    results = await svc.vector_search_facts(driver, kg_id, [0.1, 0.2], top_k=5)

    assert len(results) == 2  # 都保留，不因缺鍵而互相合併或誤判為重複
    assert {r["fact_text"] for r in results} == {"舊資料事實一", "舊資料事實二"}


@pytest.mark.asyncio
async def test_vector_search_facts_truncates_deduped_results_to_top_k():
    driver = FakeDriver(records=[
        {"fact_text": f"事實{i}", "verb": "V", "confidence": 1,
         "subject": f"S{i}", "object": f"O{i}", "rel_type": "RELATED_TO",
         "source_doc_id": "doc-1", "source_svo_chunk_index": i, "score": 1.0 - i * 0.01}
        for i in range(10)
    ])
    kg_id = uuid4()

    results = await svc.vector_search_facts(driver, kg_id, [0.1, 0.2], top_k=3)

    assert len(results) == 3
    assert [r["fact_text"] for r in results] == ["事實0", "事實1", "事實2"]


# ── backfill_fact_nodes（3.1.4 §b 回填批次任務，2026-08-18）─────────────────

class BackfillFactFakeDriver:
    """模擬「掃描既有邊＋citations_json → 存在性檢查 → 建立 Fact 節點」的
    完整鏈路，供 `backfill_fact_nodes()` 測試使用。`edges` 為固定的既有邊
    清單（模擬分頁掃描來源）；`existing_fact_keys` 模擬已經有對應 Fact 節點
    的 citation（比對鍵：source_doc_id/chunk_index/subject/rel_type/object）；
    `missing_chunk_keys` 模擬 `_create_fact_node()` 內 `MATCH (c:Chunk...)`
    找不到對應節點、整條鏈不建立任何東西的情境（(source_doc_id, chunk_index)）。"""

    def __init__(self, edges, existing_fact_keys=None, missing_chunk_keys=None):
        self._edges = edges
        self.existing_fact_keys = existing_fact_keys or set()
        self.missing_chunk_keys = missing_chunk_keys or set()
        self.scan_calls: list[dict] = []
        self.exist_calls: list[dict] = []
        self.create_calls: list[dict] = []

    async def execute_query(self, query: str, **params):
        stripped = query.strip()
        if "WHERE r.kg_id = $kg_id AND r.citations_json IS NOT NULL" in stripped:
            self.scan_calls.append(params)
            skip, batch_size = params["skip"], params["batch_size"]
            return FakeResult(self._edges[skip: skip + batch_size])
        if "RETURN count(f) AS cnt" in stripped:
            self.exist_calls.append(params)
            key = (
                params["source_doc_id"], params["chunk_index"],
                params["subject"], params["rel_type"], params["object"],
            )
            return FakeResult([{"cnt": 1 if key in self.existing_fact_keys else 0}])
        if "CREATE (f:Fact" in stripped:
            self.create_calls.append(params)
            chunk_key = (params["source_doc_id"], params["chunk_index"])
            if chunk_key in self.missing_chunk_keys:
                return FakeResult([])  # MATCH (c:Chunk...) 找不到，整條鏈不執行
            return FakeResult([{"f": params}])
        return FakeResult([])


def _fact_edge(subject="A", object_="B", rel_type="CAUSES", citations=None):
    return {
        "rel_type": rel_type, "subject": subject, "object": object_,
        "subject_type": "概念", "object_type": "概念",
        "citations_json": json.dumps(citations or []),
    }


@pytest.mark.asyncio
async def test_backfill_fact_nodes_creates_fact_for_uncovered_citation():
    doc_id = str(uuid4())
    edge = _fact_edge(citations=[
        {"source_doc_id": doc_id, "source_svo_chunk_index": 1, "verb": "導致", "confidence": 3},
    ])
    driver = BackfillFactFakeDriver(edges=[edge])
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding)

    assert count == 1
    assert len(driver.create_calls) == 1
    call = driver.create_calls[0]
    assert call["subject"] == "A"
    assert call["object"] == "B"
    assert call["rel_type"] == "CAUSES"
    assert call["source_doc_id"] == doc_id
    assert call["chunk_index"] == 1
    assert call["verb"] == "導致"
    assert call["confidence"] == 3
    assert call["fact_text"] == svc._verbalize_fact("A", "概念", "導致", "B", "概念")


@pytest.mark.asyncio
async def test_backfill_fact_nodes_threads_article_no_from_citation():
    """2026-08-24：citation 的 `article_no`（`_new_citation()` 新增欄位）應
    原樣傳入 `_create_fact_node()`，讓法規領域的回填 Fact 同樣能連向
    `LawArticle`，不因走回填路徑而漏掉這個欄位。"""
    doc_id = str(uuid4())
    edge = _fact_edge(citations=[
        {
            "source_doc_id": doc_id, "source_svo_chunk_index": 5,
            "verb": "應供應", "confidence": 3, "article_no": "第 5 條",
        },
    ])
    driver = BackfillFactFakeDriver(edges=[edge])
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding)

    assert count == 1
    assert driver.create_calls[0]["article_no"] == "第 5 條"


@pytest.mark.asyncio
async def test_backfill_fact_nodes_skips_citation_already_covered():
    """EXIST5：已有對應 Fact 節點時略過，不重複呼叫 embedding provider。"""
    doc_id = str(uuid4())
    edge = _fact_edge(citations=[
        {"source_doc_id": doc_id, "source_svo_chunk_index": 1, "verb": "導致", "confidence": 3},
    ])
    driver = BackfillFactFakeDriver(
        edges=[edge],
        existing_fact_keys={(doc_id, 1, "A", "CAUSES", "B")},
    )
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding)

    assert count == 0
    assert driver.create_calls == []


@pytest.mark.asyncio
async def test_backfill_fact_nodes_skips_citation_missing_source_info():
    edge = _fact_edge(citations=[
        {"source_doc_id": None, "source_svo_chunk_index": None, "verb": "導致", "confidence": 3},
    ])
    driver = BackfillFactFakeDriver(edges=[edge])
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding)

    assert count == 0
    assert driver.exist_calls == []
    assert driver.create_calls == []


@pytest.mark.asyncio
async def test_backfill_fact_nodes_does_not_count_when_chunk_missing():
    """`_create_fact_node()` 底層 MATCH (c:Chunk...) 找不到節點時整條鏈不建立
    任何東西——繼承既有 Chunk 雙鍵值缺口，backfill 不應計為成功建立。"""
    doc_id = str(uuid4())
    edge = _fact_edge(citations=[
        {"source_doc_id": doc_id, "source_svo_chunk_index": 1, "verb": "導致", "confidence": 3},
    ])
    driver = BackfillFactFakeDriver(edges=[edge], missing_chunk_keys={(doc_id, 1)})
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding)

    assert count == 0
    assert len(driver.create_calls) == 1  # 有嘗試過，只是未真正建立


@pytest.mark.asyncio
async def test_backfill_fact_nodes_handles_multiple_citations_on_same_edge():
    """對應『同一邊累積多筆 citation，各自獨立產生 Fact 節點』（3.1.4 §a 的
    『永不相互覆蓋或平均』設計意圖，延伸到回填路徑）。"""
    doc_id_1, doc_id_2 = str(uuid4()), str(uuid4())
    edge = _fact_edge(citations=[
        {"source_doc_id": doc_id_1, "source_svo_chunk_index": 1, "verb": "創立", "confidence": 3},
        {"source_doc_id": doc_id_2, "source_svo_chunk_index": 5, "verb": "創辦", "confidence": 2},
    ])
    driver = BackfillFactFakeDriver(edges=[edge])
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding)

    assert count == 2
    assert {c["verb"] for c in driver.create_calls} == {"創立", "創辦"}


@pytest.mark.asyncio
async def test_backfill_fact_nodes_paginates_across_multiple_batches():
    """一次性腳本內部自行分頁掃完整個 KG，不依賴外部反覆呼叫（見 §b `START5`
    節點：與接線進治理 Worker 的另外三個 backfill_* 函式不同類）。"""
    edges = [
        _fact_edge(subject=f"S{i}", object_=f"O{i}", citations=[
            {"source_doc_id": str(uuid4()), "source_svo_chunk_index": 1, "verb": "關係", "confidence": 1},
        ])
        for i in range(3)
    ]
    driver = BackfillFactFakeDriver(edges=edges)
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding, batch_size=2)

    assert count == 3
    assert len(driver.scan_calls) == 2  # 第一批 2 筆、第二批 1 筆（不足 batch_size 即停止）
    assert driver.scan_calls[0]["skip"] == 0
    assert driver.scan_calls[1]["skip"] == 2


@pytest.mark.asyncio
async def test_backfill_fact_nodes_returns_zero_when_no_edges():
    driver = BackfillFactFakeDriver(edges=[])
    embedding = FakeEmbedding()
    kg_id = uuid4()

    count = await svc.backfill_fact_nodes(driver, kg_id, embedding)

    assert count == 0
    assert len(driver.scan_calls) == 1


# ── § Phase 1 標準化 RAG：Sentence 節點與向量索引（2026-08-20）───────────────

def test_kg_sentence_label_and_index_name_are_per_kg():
    kg_id = uuid4()
    label = svc._kg_sentence_label(str(kg_id))
    index_name = svc._sentence_vector_index_name(str(kg_id))
    assert label == f"Sentence_{str(kg_id).replace('-', '_')}"
    assert index_name == f"sentence_embedding_vector_{str(kg_id).replace('-', '_')}"


@pytest.mark.asyncio
async def test_create_sentence_vector_index_without_driver_or_kg_id_is_noop():
    await svc.create_sentence_vector_index(None)  # 不應拋出例外
    driver = FakeDriver()
    await svc.create_sentence_vector_index(driver)  # kg_id 缺席同樣視為 noop
    assert driver.calls == []


@pytest.mark.asyncio
async def test_create_sentence_vector_index_issues_per_kg_create_vector_index_query():
    driver = FakeDriver()
    kg_id = uuid4()

    await svc.create_sentence_vector_index(driver, kg_id, dim=384)

    assert len(driver.calls) == 1
    query, params = driver.calls[0]
    assert svc._sentence_vector_index_name(str(kg_id)) in query
    assert f"FOR (s:{svc._kg_sentence_label(str(kg_id))}) ON s.sentence_embedding" in query
    assert params["dim"] == 384


def _make_svo_chunk(index: int, start: int, end: int) -> SVOChunk:
    return SVOChunk(
        index=index, total_chunks=1, source_sentence_start=start, source_sentence_end=end,
        text="", original_sentences=[], normalized_sentences=[],
        filename=f"svo-chunk-{index:03d}-of-001.md",
    )


@pytest.mark.asyncio
async def test_embed_standardized_sentences_creates_one_node_per_sentence():
    driver = FakeDriver()
    kg_id = uuid4()
    chunks = [_make_svo_chunk(1, 1, 5)]

    await svc.embed_standardized_sentences(
        driver, kg_id, "note.md",
        ["馬斯克創立了太空公司。", "馬斯克隨後研發了獵鷹火箭。"],
        [[0.1, 0.2], [0.3, 0.4]],
        chunks,
    )

    assert len(driver.calls) == 2
    query, params = driver.calls[0]
    assert svc._kg_sentence_label(str(kg_id)) in query
    assert params["sentence_index"] == 1
    assert params["sentence_text"] == "馬斯克創立了太空公司。"
    assert params["embedding"] == [0.1, 0.2]
    assert params["chunk_index"] == 1


@pytest.mark.asyncio
async def test_embed_standardized_sentences_uses_first_chunk_when_overlapping():
    """句子若落在多個重疊 chunk 的範圍內，取第一個（依 chunks 既有順序）
    涵蓋此句的 chunk，非任意規則——見 embed_standardized_sentences() docstring。"""
    driver = FakeDriver()
    kg_id = uuid4()
    # 句子 4 同時落在 chunk 1（1-5）與 chunk 2（4-8）範圍內
    chunks = [_make_svo_chunk(1, 1, 5), _make_svo_chunk(2, 4, 8)]
    sentences = ["s1", "s2", "s3", "s4", "s5"]
    vectors = [[float(i)] for i in range(5)]

    await svc.embed_standardized_sentences(driver, kg_id, "note.md", sentences, vectors, chunks)

    fourth_call_params = driver.calls[3][1]
    assert fourth_call_params["sentence_index"] == 4
    assert fourth_call_params["chunk_index"] == 1  # 取第一個涵蓋此句的 chunk，非 chunk 2


@pytest.mark.asyncio
async def test_embed_standardized_sentences_skips_sentence_with_no_covering_chunk():
    driver = FakeDriver()
    kg_id = uuid4()
    chunks = [_make_svo_chunk(1, 1, 1)]  # 只涵蓋第 1 句

    await svc.embed_standardized_sentences(
        driver, kg_id, "note.md", ["s1", "s2"], [[0.1], [0.2]], chunks,
    )

    assert len(driver.calls) == 1  # 第 2 句沒有涵蓋它的 chunk，略過


@pytest.mark.asyncio
async def test_embed_standardized_sentences_noop_on_length_mismatch():
    driver = FakeDriver()
    kg_id = uuid4()

    await svc.embed_standardized_sentences(
        driver, kg_id, "note.md", ["s1", "s2"], [[0.1]], [_make_svo_chunk(1, 1, 5)],
    )

    assert driver.calls == []


@pytest.mark.asyncio
async def test_vector_search_sentences_ensures_index_then_queries_it():
    driver = FakeDriver(records=[
        {"sentence_text": "馬斯克隨後研發了獵鷹火箭。", "source": "note.md",
         "chunk_index": 1, "source_doc_id": "doc-1", "score": 0.9},
    ])
    kg_id = uuid4()

    results = await svc.vector_search_sentences(driver, kg_id, [0.1, 0.2], top_k=5)

    assert results == [
        {"sentence_text": "馬斯克隨後研發了獵鷹火箭。", "source": "note.md",
         "chunk_index": 1, "source_doc_id": "doc-1", "score": 0.9},
    ]
    # 第一次呼叫是惰性索引建立，第二次才是實際 KNN 查詢
    index_query, index_params = driver.calls[0]
    assert svc._sentence_vector_index_name(str(kg_id)) in index_query
    assert index_params["dim"] == 2
    query, params = driver.calls[1]
    assert svc._sentence_vector_index_name(str(kg_id)) in query
    assert "node.sentence_text AS sentence_text" in query
    assert params["top_k"] == 5


# --- docs/報告/19：抽取完整性自我核對機制（2026-08-31 實作） ---------------


@pytest.mark.asyncio
async def test_find_uncovered_sentences_returns_all_when_no_triples():
    """第一階段完全沒抽到任何三元組時，全部句子視為未涵蓋（報告19 §3.1）。"""
    embedding = FakeEmbedding()
    sentences = ["句子一。", "句子二。"]

    uncovered = await svc._find_uncovered_sentences(sentences, [], embedding)

    assert uncovered == sentences


@pytest.mark.asyncio
async def test_find_uncovered_sentences_returns_empty_when_no_sentences():
    embedding = FakeEmbedding()
    triples = [SVOTriple(subject="A", verb="導致", object="B", rel_type="CAUSES")]

    uncovered = await svc._find_uncovered_sentences([], triples, embedding)

    assert uncovered == []


@pytest.mark.asyncio
async def test_find_uncovered_sentences_excludes_covered_sentence():
    """句子與已抽三元組文字高度相似（cosine 分數達門檻）時不列入未涵蓋。"""
    covered_sentence = "勞工因有事故必須親自處理，得請事假。"
    triple = SVOTriple(subject="勞工", verb="因有事故必須親自處理，得請", object="事假")
    triple_text = f"{triple.subject}{triple.verb}{triple.object}"
    embedding = FakeEmbedding(similar_to={covered_sentence: triple_text})

    uncovered = await svc._find_uncovered_sentences([covered_sentence], [triple], embedding)

    assert uncovered == []


@pytest.mark.asyncio
async def test_find_uncovered_sentences_flags_dissimilar_sentence():
    """句子與已抽三元組文字語意差異夠大（cosine 分數低於門檻）時列入未涵蓋
    ——對應報告18發現的真實案例：「以小時為請假單位」未被任何三元組涵蓋。"""
    uncovered_sentence = "勞工得擇定以小時為請假單位。"
    triple = SVOTriple(subject="勞工", verb="因有事故必須親自處理，得請", object="事假")
    embedding = FakeEmbedding()  # 未映射 similar_to，兩字串各自正交、cosine=0

    uncovered = await svc._find_uncovered_sentences([uncovered_sentence], [triple], embedding)

    assert uncovered == [uncovered_sentence]


@pytest.mark.asyncio
async def test_completeness_check_skips_second_call_when_no_original_sentences():
    """未提供 original_sentences 時無法做涵蓋比對，優雅降級為只呼叫一次
    LLM，行為等同直接呼叫 extract_svo_triples()。"""
    llm = FakeLLM('{"triples":[{"subject":"A","verb":"導致","object":"B","rel_type":"CAUSES"}]}')
    embedding = FakeEmbedding()

    triples = await svc.extract_svo_triples_with_completeness_check("A 導致 B。", [], llm, embedding)

    assert len(triples) == 1
    assert len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_completeness_check_skips_second_call_when_no_embedding_provider():
    """embedding_provider 為 None 時無法做涵蓋比對，同樣優雅降級。"""
    llm = FakeLLM('{"triples":[{"subject":"A","verb":"導致","object":"B","rel_type":"CAUSES"}]}')

    triples = await svc.extract_svo_triples_with_completeness_check(
        "A 導致 B。", ["A 導致 B。"], llm, None,
    )

    assert len(triples) == 1
    assert len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_completeness_check_skips_second_call_when_fully_covered(monkeypatch):
    """涵蓋比對沒抓到任何未涵蓋句子時，不觸發第二次 LLM 呼叫——成本模型
    對稱於報告16接地核對機制：只有真的偵測到問題才多花一次呼叫（報告19 §5）。

    monkeypatch `_reconcile_rel_type()` 為直接採信：本測試要驗證的是完整性
    核對本身的呼叫次數，`_reconcile_rel_type()` 的 ESCALATE3 仲裁是既有、
    與本次新機制無關的另一套邏輯，FakeEmbedding 的雜湊向量無法保證與 35 個
    真實型別描述句一致，會引入不相關的額外 LLM 呼叫使計數斷言不穩定。
    """
    async def fake_reconcile(verb, llm_rel_type, **kwargs):
        return llm_rel_type
    monkeypatch.setattr(svc, "_reconcile_rel_type", fake_reconcile)

    sentence = "勞工因有事故必須親自處理，得請事假。"
    llm = FakeLLM(
        '{"triples":[{"subject":"勞工","verb":"因有事故必須親自處理，得請",'
        '"object":"事假","rel_type":"RELATED_TO"}]}'
    )
    embedding = FakeEmbedding(similar_to={sentence: "勞工因有事故必須親自處理，得請事假"})

    triples = await svc.extract_svo_triples_with_completeness_check(
        sentence, [sentence], llm, embedding,
    )

    assert len(triples) == 1
    assert len(llm.prompts) == 1  # 第二次呼叫未觸發


@pytest.mark.asyncio
async def test_completeness_check_triggers_supplement_and_merges_when_uncovered(monkeypatch):
    """有未涵蓋句子時觸發第二次針對性補抽，結果併入第一階段——對應報告18
    發現的真實案例：第一階段漏抓「以小時為請假單位」，第二階段應補上。

    monkeypatch `_reconcile_rel_type()` 理由同上一則測試。"""
    async def fake_reconcile(verb, llm_rel_type, **kwargs):
        return llm_rel_type
    monkeypatch.setattr(svc, "_reconcile_rel_type", fake_reconcile)

    main_sentence = "勞工因有事故必須親自處理，得請事假。"
    missed_sentence = "勞工得擇定以小時為請假單位。"
    llm = SequencedFakeLLM([
        '{"triples":[{"subject":"勞工","verb":"因有事故必須親自處理，得請",'
        '"object":"事假","rel_type":"RELATED_TO"}]}',
        '{"triples":[{"subject":"事假","verb":"得以","object":"小時為請假單位",'
        '"rel_type":"RELATED_TO"}]}',
    ])
    embedding = FakeEmbedding()  # 兩句彼此正交，missed_sentence 不會被判定為已涵蓋

    triples = await svc.extract_svo_triples_with_completeness_check(
        f"{main_sentence}\n{missed_sentence}", [main_sentence, missed_sentence], llm, embedding,
    )

    assert len(llm.prompts) == 2  # 第一階段 + 針對性補抽各一次
    subjects = {(t.subject, t.verb, t.object) for t in triples}
    assert ("勞工", "因有事故必須親自處理，得請", "事假") in subjects
    assert ("事假", "得以", "小時為請假單位") in subjects


@pytest.mark.asyncio
async def test_completeness_check_dedupes_supplement_against_first_pass(monkeypatch):
    """補抽結果若與第一階段已有的三元組完全重複（同一組 subject/verb/object），
    合併時應去重，不重複計入。monkeypatch `_reconcile_rel_type()` 理由同上。"""
    async def fake_reconcile(verb, llm_rel_type, **kwargs):
        return llm_rel_type
    monkeypatch.setattr(svc, "_reconcile_rel_type", fake_reconcile)

    sentence = "勞工因有事故必須親自處理，得請事假。"
    duplicate_payload = (
        '{"triples":[{"subject":"勞工","verb":"因有事故必須親自處理，得請",'
        '"object":"事假","rel_type":"RELATED_TO"}]}'
    )
    llm = SequencedFakeLLM([duplicate_payload, duplicate_payload])
    embedding = FakeEmbedding()  # 未映射 similar_to → 判定為未涵蓋，觸發補抽

    triples = await svc.extract_svo_triples_with_completeness_check(
        sentence, [sentence], llm, embedding,
    )

    assert len(llm.prompts) == 2
    assert len(triples) == 1  # 重複三元組已去重


# --- docs/報告/20：抽取數值忠實性核對（2026-08-31 實作） -------------------


def test_contains_ungrounded_quantity_flags_number_not_in_source():
    """對應報告19§10真實案例：「三至七日」被錯抽成同文件另一條文的
    「一至三日」，物件裡的數量片語未逐字出現在這個chunk原文裡。"""
    source_text = "有左列情事之一者，給予三至七日之特別休假：一、主動破獲叛亂組織，人證俱獲者。"
    assert svc._contains_ungrounded_quantity("給予一至三日之特別休假", source_text) is True


def test_contains_ungrounded_quantity_passes_number_in_source():
    source_text = "有左列情事之一者，給予三至七日之特別休假：一、主動破獲叛亂組織，人證俱獲者。"
    assert svc._contains_ungrounded_quantity("給予三至七日之特別休假", source_text) is False


def test_contains_ungrounded_quantity_ignores_text_without_quantity():
    """subject／object 完全沒有數量/期限用字時，無從判定忠實性，不誤殺。"""
    source_text = "勞工因有事故必須親自處理，得請事假。"
    assert svc._contains_ungrounded_quantity("勞工", source_text) is False
    assert svc._contains_ungrounded_quantity("事假", source_text) is False


def test_filter_ungrounded_quantity_triples_drops_only_ungrounded():
    source_text = "有左列情事之一者，給予三至七日之特別休假：一、主動破獲叛亂組織，人證俱獲者。"
    grounded = SVOTriple(subject="主動破獲叛亂組織，人證俱獲者", verb="給予", object="三至七日之特別休假")
    ungrounded = SVOTriple(subject="主動破獲叛亂組織，人證俱獲者", verb="給予", object="一至三日之特別休假")

    result = svc._filter_ungrounded_quantity_triples([grounded, ungrounded], source_text)

    assert result == [grounded]


@pytest.mark.asyncio
async def test_completeness_check_drops_triple_with_ungrounded_quantity(monkeypatch):
    """端到端：extract_svo_triples_with_completeness_check() 回傳前套用
    數值忠實性核對，含跨條文挪用數字的三元組應被丟棄。"""
    async def fake_reconcile(verb, llm_rel_type, **kwargs):
        return llm_rel_type
    monkeypatch.setattr(svc, "_reconcile_rel_type", fake_reconcile)

    text = "有左列情事之一者，給予三至七日之特別休假：一、主動破獲叛亂組織，人證俱獲者。"
    llm = FakeLLM(
        '{"triples":['
        '{"subject":"主動破獲叛亂組織，人證俱獲者","verb":"給予","object":"三至七日之特別休假","rel_type":"RELATED_TO"},'
        '{"subject":"主動破獲叛亂組織，人證俱獲者","verb":"給予","object":"一至三日之特別休假","rel_type":"RELATED_TO"}'
        ']}'
    )
    embedding = FakeEmbedding()

    triples = await svc.extract_svo_triples_with_completeness_check(text, [text], llm, embedding)

    assert len(triples) == 1
    assert triples[0].object == "三至七日之特別休假"
