"""SVO 三元組提取、Neo4j MERGE、BFS 查詢。"""
from __future__ import annotations
import json
import re
from uuid import UUID

from neo4j import AsyncDriver

from core.constants import SVO_REL_TYPES
from core.providers.base import LLMProvider
from models.knowledge_graph import SVOTriple


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


async def merge_triples_to_graph(driver: AsyncDriver, kg_id: UUID, triples: list[SVOTriple]) -> None:
    """將 SVO triples MERGE 進 Neo4j Entity Graph。"""
    kg_id_str = str(kg_id)
    for triple in triples:
        rel_type = _relationship_type(triple.rel_type)
        query = f"""
        MERGE (s:Entity {{kg_id: $kg_id, name: $subject}})
        ON CREATE SET s.type = $subject_type
        MERGE (o:Entity {{kg_id: $kg_id, name: $object}})
        ON CREATE SET o.type = $object_type
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
            subject=triple.subject,
            subject_type=triple.subject_type,
            object=triple.object,
            object_type=triple.object_type,
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
