"""SVO 三元組提取、Neo4j MERGE、BFS 查詢。"""
from __future__ import annotations
import difflib
import json
import re
from uuid import UUID

from neo4j import AsyncDriver

from core.constants import (
    ENTITY_DEDUP_COSINE_THRESHOLD,
    ENTITY_DEDUP_EDIT_RATIO_THRESHOLD,
    ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD,
    SVO_REL_TYPES,
)
from core.providers.base import EmbeddingProvider, LLMProvider
from models.knowledge_graph import SVOTriple
from services.classify_service import cosine_similarity
from services.entity_registry_service import should_promote_by_frequency


async def create_entity_index(driver: AsyncDriver | None = None) -> None:
    """建立 Entity 節點索引（app 啟動時呼叫一次）。"""
    if driver is None:
        return
    await driver.execute_query(
        "CREATE INDEX entity_kg_name IF NOT EXISTS FOR (e:Entity) ON (e.kg_id, e.name)"
    )


def _strip_json_fence(raw: str) -> str:
    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else cleaned


def _parse_triples_payload(raw: str) -> list[dict]:
    payload = json.loads(_strip_json_fence(raw))
    if isinstance(payload, dict):
        payload = payload.get("triples", [])
    if not isinstance(payload, list):
        raise ValueError("SVO 抽取結果必須是 JSON list 或含 triples 的 object")
    return [item for item in payload if isinstance(item, dict)]


def _svo_prompt(text: str) -> str:
    rel_types = ", ".join(sorted(SVO_REL_TYPES))
    return f"""你是知識圖譜 SVO 抽取器。
請只輸出 JSON，不要輸出解釋。從文本抽取符合受控關係詞彙的三元組。

合法 rel_type：
{rel_types}

輸出格式：
{{"triples":[{{"subject":"", "subject_type":"概念", "rel_type":"RELATED_TO", "verb":"", "object":"", "object_type":"概念", "confidence":1}}]}}

規則：
1. rel_type 必須完全等於合法清單中的一個值。
2. verb 保留原文中的自然語言關係描述。
3. confidence 使用 1 到 5 的整數。
4. 沒有可判定三元組時輸出 {{"triples":[]}}。

文本：
{text}
"""


async def extract_svo_triples(text: str, llm_provider: LLMProvider | None = None) -> list[SVOTriple]:
    """用 LLM 抽取受控關係 SVO triples。

    未提供 provider 時回傳空清單，讓離線管線與單元測試可以安全呼叫；實際抽取
    Worker 應明確傳入本地或雲端 LLMProvider。
    """
    if not text.strip() or llm_provider is None:
        return []

    raw = await llm_provider.generate_json(_svo_prompt(text))
    triples: list[SVOTriple] = []
    for item in _parse_triples_payload(raw):
        rel_type = str(item.get("rel_type", "RELATED_TO")).strip()
        if rel_type not in SVO_REL_TYPES:
            continue
        item["rel_type"] = rel_type
        try:
            triples.append(SVOTriple(**item))
        except Exception:
            continue
    return triples


def _relationship_type(rel_type: str) -> str:
    if rel_type not in SVO_REL_TYPES:
        raise ValueError(f"不合法的 SVO rel_type: {rel_type}")
    return f"`{rel_type}`"


# ── 實體對齊/去重（3.1.4 DEDUP4／3.4 §b ESCALATE＋RECHECK，2026-07-21 新增；
#    2026-07-21 再修訂：改用 (Chunk)-[:HAS_ENTITY {surface_form}]->(Entity)
#    邊聚合頻率，取代原本存在 Entity 節點上的 alias_counts_json，與
#    docs/論文/03_系統設計與方法論.md § 3.4 §b 的文字描述（含 RECORD3B／
#    RECHECK 的 Cypher 範例）保持一致，不再是兩套不同的資料模型）─────────────

async def _fetch_entity_candidates(driver: AsyncDriver, kg_id: UUID, entity_type: str) -> list[dict]:
    """查詢同 KG、同類型的既有 Entity 節點（僅名稱，供編輯距離/cosine 比對）。"""
    result = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id, type: $entity_type}) RETURN e.name AS name",
        kg_id=str(kg_id), entity_type=entity_type,
    )
    return [dict(r) for r in result.records]


def _edit_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


async def resolve_entity_name(
    name: str,
    candidates: list[dict],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> str:
    """DEDUP4＋ESCALATE：決定這次提及該歸屬到哪個既有 Entity 名稱。

    依序：① 與既有名稱編輯距離高度相似（如「台積電」對「台積電公司」）直接
    視為同一實體；② 無命中則做 cosine 相似度比對（需 `embedding_provider`，
    未提供時視為新實體，不強行比對）；③ cosine 落在 ESCALATE 灰色地帶
    （既有門檻與更低下限之間）時，若有 `llm_provider` 則呼叫 LLM 仲裁；
    皆未命中則回傳原名，代表應建立新節點。門檻定義見 core/constants.py。
    """
    if not candidates:
        return name

    for c in candidates:
        if c["name"] == name:
            return name
        if _edit_ratio(name, c["name"]) >= ENTITY_DEDUP_EDIT_RATIO_THRESHOLD:
            return c["name"]

    if embedding_provider is None:
        return name

    name_vec = embedding_provider.encode(name)
    best_name: str | None = None
    best_score = 0.0
    for c in candidates:
        score = cosine_similarity(name_vec, embedding_provider.encode(c["name"]))
        if score > best_score:
            best_score = score
            best_name = c["name"]

    if best_name is None:
        return name
    if best_score >= ENTITY_DEDUP_COSINE_THRESHOLD:
        return best_name

    if llm_provider is not None and best_score >= ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD:
        prompt = (
            f"「{name}」與「{best_name}」是否為同一個真實世界的實體/對象？"
            "只回答「是」或「否」，不要有其他文字。"
        )
        answer = (await llm_provider.generate(prompt)).strip()
        if answer.startswith("是"):
            return best_name

    return name


async def _merge_chunk_mention(
    driver: AsyncDriver,
    kg_id: UUID,
    entity_name: str,
    entity_type: str,
    surface_form: str,
    source_doc_id: UUID | None,
    source_svo_chunk_index: int | None,
    source_svo_chunk_file: str | None,
) -> None:
    """RECORD3B：建立/合併 `(Chunk)-[:HAS_ENTITY {surface_form}]->(Entity)` 邊。

    Chunk 節點以 `(kg_id, source_doc_id, chunk_index)` 為識別鍵；`surface_form`
    是 `HAS_ENTITY` 邊 MERGE 樣式的一部分，同一 chunk 內重複提及同一別名不會
    產生多筆邊，跨 chunk 才會累積出不同的邊，供 `_aggregate_alias_counts()`
    做跨文件頻率聚合（3.4 §b RECHECK 的資料來源）。
    """
    await driver.execute_query(
        """
        MERGE (c:Chunk {kg_id: $kg_id, source_doc_id: $source_doc_id, chunk_index: $chunk_index})
        ON CREATE SET c.chunk_file = $chunk_file
        MERGE (e:Entity {kg_id: $kg_id, name: $entity_name})
        ON CREATE SET e.type = $entity_type
        MERGE (c)-[r:HAS_ENTITY {surface_form: $surface_form}]->(e)
        """,
        kg_id=str(kg_id),
        source_doc_id=str(source_doc_id),
        chunk_index=source_svo_chunk_index,
        chunk_file=source_svo_chunk_file,
        entity_name=entity_name,
        entity_type=entity_type,
        surface_form=surface_form,
    )


async def _aggregate_alias_counts(driver: AsyncDriver, kg_id: UUID, entity_name: str) -> dict[str, int]:
    """依 3.4 §b 文字描述的 Cypher 範例，聚合該實體所有 `HAS_ENTITY` 邊的
    `surface_form` 出現次數。

    **2026-07-21 修訂（使用者提出）**：計數單位是**獨立文件數**
    （`count(DISTINCT c.source_doc_id)`），不是邊的總數（`count(*)`）——
    §a 已把單一文件內的所有變體收斂成一個「文件內暫定標準名」，若按邊數
    計（每個 chunk 各算一次），單一文件只要 chunk 數量多，就會讓它選中的
    別名在跨文件頻率上被灌票，不代表真正有更多文件認同這個稱呼。改成數
    獨立文件數，才是「一份文件一票」的跨文件共識，對應 Wikidata／CESI
    文獻描述的頻率概念（見模組層級 docstring）。
    """
    result = await driver.execute_query(
        """
        MATCH (c:Chunk {kg_id: $kg_id})-[r:HAS_ENTITY]->(e:Entity {kg_id: $kg_id, name: $entity_name})
        RETURN r.surface_form AS alias, count(DISTINCT c.source_doc_id) AS freq
        """,
        kg_id=str(kg_id), entity_name=entity_name,
    )
    return {record["alias"]: record["freq"] for record in result.records}


async def merge_entity(
    driver: AsyncDriver,
    kg_id: UUID,
    name: str,
    entity_type: str,
    surface_form: str,
    *,
    source_doc_id: UUID | None = None,
    source_svo_chunk_index: int | None = None,
    source_svo_chunk_file: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> str:
    """解析並合併一個實體節點，回傳這次寫入後的最終 Entity.name。

    對應 3.1.4 DEDUP4／3.4 §b ESCALATE＋RECORD3B＋RECHECK：先決定這次提及該
    歸屬到哪個既有實體（`resolve_entity_name`，或視為新實體），記錄
    `(Chunk)-[:HAS_ENTITY {surface_form}]->(Entity)` 邊，再依跨文件累積的
    `surface_form` 頻率（`_aggregate_alias_counts`，以獨立文件數計，見該函式
    docstring）決定是否需要把 `Entity.name` 更新為更常見的別名——**主規則與
    3.4 §a 文件內『暫定標準名』不同**（2026-07-21 使用者提出修訂）：§a
    （`entity_registry_service.should_promote_by_length`）以長度優先為主規則，
    這裡（`should_promote_by_frequency`）以跨文件頻率優先為主規則，兩者衡量
    範圍不同、權威層級也不同（§a 僅供文件內部處理參考，這裡才是寫入圖譜的
    權威判斷）；頻率優先規則的文獻依據（Wikidata／CESI）本來就是跨文件/跨
    編者尺度的概念，套用在這一層（§b）比先前套用在單一文件內（§a）更貼切。

    `source_doc_id`／`source_svo_chunk_index` 缺席時（例如呼叫端尚未提供
    chunk 追溯資訊），跳過 `HAS_ENTITY` 邊建立與頻率提升判斷，只單純
    MERGE 實體節點——此時無法判斷是否要提升標準名，保留現狀最保守。

    ⚠️ **效能待決策**：`_fetch_entity_candidates`／`_aggregate_alias_counts`
    對每次呼叫都重新查詢，Hub 型 KG 規模變大後可能有效能疑慮，留待第四章
    實作與第五章消融實驗評估，非本設計階段的阻斷性問題（比照 3.1.1 §a
    未分配池 O(n²) 的既有處理方式）。
    """
    candidates = await _fetch_entity_candidates(driver, kg_id, entity_type)
    resolved_name = await resolve_entity_name(
        name, candidates, embedding_provider=embedding_provider, llm_provider=llm_provider
    )

    if source_doc_id is None or source_svo_chunk_index is None:
        await driver.execute_query(
            "MERGE (e:Entity {kg_id: $kg_id, name: $name}) ON CREATE SET e.type = $entity_type",
            kg_id=str(kg_id), name=resolved_name, entity_type=entity_type,
        )
        return resolved_name

    await _merge_chunk_mention(
        driver, kg_id, resolved_name, entity_type, surface_form,
        source_doc_id, source_svo_chunk_index, source_svo_chunk_file,
    )
    alias_counts = await _aggregate_alias_counts(driver, kg_id, resolved_name)

    final_name = resolved_name
    current_count = alias_counts.get(resolved_name, 0)
    candidate_count = alias_counts.get(surface_form, 0)
    if surface_form != resolved_name and should_promote_by_frequency(
        candidate_count, current_count, surface_form, resolved_name
    ):
        final_name = surface_form  # RECHECK/UPDATENAME：標準名隨語料持續擴增而更新

    await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id, name: $resolved_name}) SET e.name = $final_name, e.aliases = $aliases",
        kg_id=str(kg_id),
        resolved_name=resolved_name,
        final_name=final_name,
        aliases=list(alias_counts.keys()),
    )
    return final_name


async def merge_triples_to_graph(
    driver: AsyncDriver,
    kg_id: UUID,
    triples: list[SVOTriple],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> None:
    """將 SVO triples 的主客實體解析對齊後，MERGE 進 Neo4j Entity Graph。

    `embedding_provider`／`llm_provider` 皆為可選——未提供時，實體解析僅做
    編輯距離比對（跳過 cosine 與 LLM 仲裁兩層），行為退化為較保守的去重，
    讓離線管線與單元測試可以安全呼叫，不強制要求外部服務。
    """
    kg_id_str = str(kg_id)
    for triple in triples:
        rel_type = _relationship_type(triple.rel_type)
        subject_name = await merge_entity(
            driver, kg_id, triple.subject, triple.subject_type, triple.subject,
            source_doc_id=triple.source_doc_id,
            source_svo_chunk_index=triple.source_svo_chunk_index,
            source_svo_chunk_file=triple.source_svo_chunk_file,
            embedding_provider=embedding_provider, llm_provider=llm_provider,
        )
        object_name = await merge_entity(
            driver, kg_id, triple.object, triple.object_type, triple.object,
            source_doc_id=triple.source_doc_id,
            source_svo_chunk_index=triple.source_svo_chunk_index,
            source_svo_chunk_file=triple.source_svo_chunk_file,
            embedding_provider=embedding_provider, llm_provider=llm_provider,
        )
        query = f"""
        MATCH (s:Entity {{kg_id: $kg_id, name: $subject}})
        MATCH (o:Entity {{kg_id: $kg_id, name: $object}})
        MERGE (s)-[r:{rel_type} {{
            kg_id: $kg_id,
            verb: $verb,
            source_doc_id: $source_doc_id,
            source_svo_chunk_index: $source_svo_chunk_index,
            source_sentence_start: $source_sentence_start,
            source_sentence_end: $source_sentence_end
        }}]->(o)
        SET r.confidence = $confidence,
            r.source_svo_chunk_file = $source_svo_chunk_file
        """
        await driver.execute_query(
            query,
            kg_id=kg_id_str,
            subject=subject_name,
            object=object_name,
            verb=triple.verb,
            confidence=triple.confidence,
            source_doc_id=str(triple.source_doc_id) if triple.source_doc_id else None,
            source_svo_chunk_index=triple.source_svo_chunk_index,
            source_svo_chunk_file=triple.source_svo_chunk_file,
            source_sentence_start=triple.source_sentence_start,
            source_sentence_end=triple.source_sentence_end,
        )


async def bfs_query(driver: AsyncDriver, kg_id: UUID, seed_entities: list[str], hops: int = 2) -> list[SVOTriple]:
    """從 seed entity 做 bounded BFS，回傳路徑上的去重 SVO triples。"""
    seeds = [entity.strip() for entity in seed_entities if entity.strip()]
    if not seeds:
        return []
    if hops < 1 or hops > 5:
        raise ValueError("hops 必須介於 1 到 5")

    result = await driver.execute_query(
        f"""
        MATCH (seed:Entity {{kg_id: $kg_id}})
        WHERE seed.name IN $seed_entities
        MATCH path = (seed)-[*1..{hops}]-(neighbor:Entity {{kg_id: $kg_id}})
        UNWIND relationships(path) AS rel
        WITH DISTINCT startNode(rel) AS s, rel, endNode(rel) AS o
        RETURN
            s.name AS subject,
            coalesce(s.type, "概念") AS subject_type,
            type(rel) AS rel_type,
            coalesce(rel.verb, type(rel)) AS verb,
            o.name AS object,
            coalesce(o.type, "概念") AS object_type,
            coalesce(rel.confidence, 1) AS confidence,
            rel.source_doc_id AS source_doc_id,
            rel.source_svo_chunk_index AS source_svo_chunk_index,
            rel.source_svo_chunk_file AS source_svo_chunk_file,
            rel.source_sentence_start AS source_sentence_start,
            rel.source_sentence_end AS source_sentence_end
        """,
        kg_id=str(kg_id),
        seed_entities=seeds,
    )

    triples: list[SVOTriple] = []
    for record in result.records:
        payload = dict(record)
        if payload.get("source_doc_id"):
            payload["source_doc_id"] = UUID(payload["source_doc_id"])
        triples.append(SVOTriple(**payload))
    return triples
