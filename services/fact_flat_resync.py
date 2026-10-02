"""Fact 扁平屬性重同步（報告244 方案 B；報告246 原型驗證、報告250 正式模組化）。

Fact 節點的 `subject`／`object`／`rel_type` 是建立時從實體抄來的，實體之後被改名就會過時。
本模組提供獨立、冪等、預設 `dry_run` 的重同步函式；不改任何既有熱路徑，也不被任何程式接線。
driver 由呼叫者傳入（只用 `driver.execute_query(statement, **params)`，回傳物件需有 `.records`）。
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

SYNC_ATTRIBUTES = ("subject", "object", "rel_type")


async def cypher(driver: Any, statement: str, **parameters: Any):
    return await driver.execute_query(statement, **parameters)


def _new_stats() -> dict[str, int]:
    return {
        "subject_changed": 0,
        "object_changed": 0,
        "rel_type_changed": 0,
        "rel_type_skipped_multi_edge": 0,
        "rel_type_skipped_no_edge": 0,
        "unchanged": 0,
        "facts_without_links": 0,
    }


async def _fact_sync_rows(driver: Any, kg_id: UUID, *, sync_rel_type: bool) -> list[dict[str, Any]]:
    edge_subquery = """
    CALL {
        WITH s, o
        OPTIONAL MATCH (s)-[r]->(o)
        WHERE s IS NOT NULL AND o IS NOT NULL
          AND r.kg_id = $kg_id AND r.citations_json IS NOT NULL
        RETURN count(r) AS edge_count, collect(DISTINCT type(r)) AS edge_types
    }
    """ if sync_rel_type else """
    WITH f, s, o, 0 AS edge_count, [] AS edge_types
    """
    result = await cypher(
        driver,
        f"""
        MATCH (f:Fact {{kg_id: $kg_id}})
        CALL {{
            WITH f
            OPTIONAL MATCH (f)-[:HAS_SUBJECT]->(s:Entity)
            RETURN collect(s)[0] AS s
        }}
        CALL {{
            WITH f
            OPTIONAL MATCH (f)-[:HAS_OBJECT]->(o:Entity)
            RETURN collect(o)[0] AS o
        }}
        {edge_subquery}
        RETURN elementId(f) AS eid,
               f.subject AS flat_subject, f.object AS flat_object, f.rel_type AS flat_rel_type,
               s IS NOT NULL AS subject_exists, o IS NOT NULL AS object_exists,
               s.name AS subject_name, o.name AS object_name,
               edge_count, edge_types
        ORDER BY elementId(f)
        """,
        kg_id=str(kg_id),
    )
    return [dict(record) for record in result.records]


def _plan_resync_updates(
    rows: list[dict[str, Any]], *, sync_rel_type: bool
) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    """計畫階段（純函式）：不接收 driver、不寫入。"""

    stats = _new_stats()
    updates: dict[str, list[dict[str, Any]]] = {name: [] for name in SYNC_ATTRIBUTES}
    for row in rows:
        if not row["subject_exists"] or not row["object_exists"]:
            stats["facts_without_links"] += 1
            continue

        changed = False
        if row["subject_name"] is not None and row["flat_subject"] != row["subject_name"]:
            stats["subject_changed"] += 1
            updates["subject"].append({"eid": row["eid"], "value": row["subject_name"]})
            changed = True
        if row["object_name"] is not None and row["flat_object"] != row["object_name"]:
            stats["object_changed"] += 1
            updates["object"].append({"eid": row["eid"], "value": row["object_name"]})
            changed = True

        if sync_rel_type:
            edge_count = int(row["edge_count"] or 0)
            edge_types = list(row["edge_types"] or [])
            if edge_count == 1 and len(edge_types) == 1:
                if row["flat_rel_type"] != edge_types[0]:
                    stats["rel_type_changed"] += 1
                    updates["rel_type"].append({"eid": row["eid"], "value": edge_types[0]})
                    changed = True
            elif edge_count > 1:
                stats["rel_type_skipped_multi_edge"] += 1
            else:
                stats["rel_type_skipped_no_edge"] += 1

        if not changed:
            stats["unchanged"] += 1
    return stats, updates


async def _apply_updates(driver: Any, kg_id: UUID, updates: dict[str, list[dict[str, Any]]]) -> None:
    # 屬性名以 f-string 插入 Cypher，白名單是防注入的唯一保證；先全數檢查再寫，避免部分寫入。
    for attribute in updates:
        if attribute not in SYNC_ATTRIBUTES:
            raise ValueError(f"不允許同步的屬性：{attribute!r}（白名單：{SYNC_ATTRIBUTES}）")
    for attribute, rows in updates.items():
        if not rows:
            continue
        result = await cypher(
            driver,
            f"""
            UNWIND $updates AS update
            MATCH (f:Fact {{kg_id: $kg_id}})
            WHERE elementId(f) = update.eid
            SET f.{attribute} = update.value
            RETURN count(f) AS updated
            """,
            kg_id=str(kg_id),
            updates=rows,
        )
        updated = int(result.records[0]["updated"] if result.records else 0)
        if updated != len(rows):
            raise RuntimeError(f"方案 B 寫入數量不符：{attribute} expected={len(rows)} actual={updated}")


async def resync_fact_flat_properties(
    driver: Any,
    kg_id: UUID,
    *,
    dry_run: bool = True,
    sync_rel_type: bool = False,
) -> dict[str, int]:
    """把 Fact 的扁平屬性 `subject`／`object`（可選 `rel_type`）重同步為目前實體名稱／邊型別。

    - 預設 `dry_run=True`：只讀、只回傳統計，絕不送出任何寫入語句。
    - 冪等：套用後再跑一次，三個 `*_changed` 皆為 0。
    - `sync_rel_type=True` 的保守規則：端點間恰好一條邊且只有一種型別才同步；
      多條邊（`rel_type_skipped_multi_edge`）或無邊（`rel_type_skipped_no_edge`）一律略過。
    - 只改 `subject`／`object`／`rel_type` 三個屬性；**不碰** `fact_text`、`fact_embedding`、
      `natural_text`、`verb_embedding`。同步後必須再跑既有 `backfill_fact_text_embeddings`
      才會重建 `fact_text` 與向量。
    - 對 KG#4 套用（`dry_run=False`）前須先備份並取得使用者同意（報告244 §6、報告249）。
    """

    rows = await _fact_sync_rows(driver, kg_id, sync_rel_type=sync_rel_type)
    stats, updates = _plan_resync_updates(rows, sync_rel_type=sync_rel_type)
    if not dry_run:
        await _apply_updates(driver, kg_id, updates)
    return stats
