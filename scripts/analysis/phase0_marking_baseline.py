"""Phase 0 零寫入派生報表：四個對象 × 三種標示（報告207 K2）。

把「不適用／未知／尚未處理」套用到 KG#4 現有資料，**只量測、不寫入**，並產出基準線
（已有明確標示比例／可唯讀推算比例／需人工或 LLM 比例）。三種標示的操作型定義見報告201 §0。

防護（與 semantic_layer_invariants.py 相同）：重用其 `assert_read_only()` 白名單（不放寬）；
session 為 `default_access_mode=READ`；不呼叫 LLM／embedding；執行前後總數須為 57,451／137,873／16,826／12,296。
匯入本模組**不得**改 `os.environ`、不得連線、不得匯入 `neo4j`／`core`／`services`
（`core.constants` 僅在 main 內延遲匯入）。純運算函式（`classify_*`、`tally_*`、`build_baseline`）可單元測試。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.semantic_layer_invariants import (  # noqa: E402
    BOLT_URI_DEFAULT,
    EXPECTED_TOTALS,
    KG_ID_DEFAULT,
    ReadOnlyRunner,
    assert_read_only,  # noqa: F401  (re-export：測試與呼叫端確認同一白名單)
    classify_type_tokens,
    normalize_type_key,
    parse_citations,
    totals,
)

PLACEHOLDER_CONCEPT = "概念"

# 資料中是否已有「標示」欄位：依屬性鍵名稱樣式粗篩（只報出候選鍵，由人判讀）
_MARKER_KEY_RE = re.compile(r"(status|state|origin|scope|marker|placeholder|unknown|pending|n_?a$|applicab)", re.IGNORECASE)


# ── ① 實體型別 ───────────────────────────────────────────────────────────────
def classify_entity_type(raw_type: str | None, core_lookup: dict[str, str], ext_lookup: dict[str, str]) -> str:
    """回傳 empty／concept_only／standard／standard_with_concept／outside_raw。

    - empty：空值或全空白
    - concept_only：所有 token 皆為「概念」（預設佔位 vs. 真的是概念——無法由現有資料判定）
    - standard：全部 token 在核心 52 或擴充 939 表內
    - standard_with_concept：含「概念」且其餘 token 皆標準
    - outside_raw：含任一不在核心／擴充表、且不是「概念」的原字串 token
    """
    toks = classify_type_tokens(raw_type, core_lookup, ext_lookup)
    if not toks:
        return "empty"
    has_concept = any(t == PLACEHOLDER_CONCEPT for t, _ in toks)
    others = [(t, c) for t, c in toks if t != PLACEHOLDER_CONCEPT]
    if not others:
        return "concept_only"
    if any(c == "outside" for _, c in others):
        return "outside_raw"
    return "standard_with_concept" if has_concept else "standard"


def tally_entity_types(rows: Iterable[tuple[str | None, int]], core_lookup: dict[str, str], ext_lookup: dict[str, str]) -> dict[str, int]:
    """rows＝(原始 type 字串, 實體數)；回傳各類別實體數。"""
    out: Counter[str] = Counter()
    for raw, n in rows:
        out[classify_entity_type(raw, core_lookup, ext_lookup)] += n
    for k in ("empty", "concept_only", "standard", "standard_with_concept", "outside_raw"):
        out.setdefault(k, 0)
    return dict(out)


def entity_type_marks(cat: dict[str, int]) -> dict[str, Any]:
    """三種標示＋已解決＋無法判定。「概念」兩種算法並列（A＝視為未知佔位；B＝視為真的概念）。

    三種標示的對應依報告201 §1.2：未知＝空值；尚未處理＝原字串（235 種）；不適用＝目前無此概念（0，待使用者決定）。
    """
    total = sum(cat.values())
    resolved = cat["standard"] + cat["standard_with_concept"]
    base = {"不適用": 0, "未知": cat["empty"], "尚未處理": cat["outside_raw"], "已解決": resolved,
            "無法由現有資料判定": cat["concept_only"]}
    return {
        "total": total,
        "strict": base,
        "scheme_A_concept_as_unknown": {**base, "未知": cat["empty"] + cat["concept_only"], "無法由現有資料判定": 0},
        "scheme_B_concept_as_real": {**base, "已解決": resolved + cat["concept_only"], "無法由現有資料判定": 0},
    }


# ── ② 關係型別 ───────────────────────────────────────────────────────────────
def tally_rel_types(rows: Iterable[tuple[str | None, bool, int]]) -> dict[str, int]:
    """rows＝(Fact.rel_type, verb 是否為空, Fact 數)。

    非 RELATED_TO＝已解決（可確定為 LLM 選的詞彙內型別）；RELATED_TO 來源不明（刻意／缺 rel_type／詞彙外／仲裁皆非，
    報告201 §2.1 讀碼確認無法由資料區分）。
    """
    out = {"declared_non_related_to": 0, "related_to_with_verb": 0, "related_to_empty_verb": 0, "rel_type_null": 0}
    for t, verb_empty, n in rows:
        if t is None:
            out["rel_type_null"] += n
        elif t != "RELATED_TO":
            out["declared_non_related_to"] += n
        elif verb_empty:
            out["related_to_empty_verb"] += n
        else:
            out["related_to_with_verb"] += n
    return out


def rel_type_marks(c: dict[str, int]) -> dict[str, Any]:
    total = sum(c.values())
    related = c["related_to_with_verb"] + c["related_to_empty_verb"]
    return {
        "total": total,
        "strict": {"不適用": 0, "已解決": c["declared_non_related_to"], "無法由現有資料判定（RELATED_TO 來源不明）": related + c["rel_type_null"]},
        "scheme_RD_related_to_as_unknown": {"不適用": 0, "已解決": c["declared_non_related_to"], "未知（來源不明）": related + c["rel_type_null"]},
    }


def tally_edge_verb_embedding(rows: Iterable[tuple[str, bool, int]]) -> dict[str, int]:
    """rows＝(邊型別, 是否有 verb_embedding, 邊數)。僅描述分布；verb_embedding 不是兜底專屬標記（報告201 §2.1）。"""
    out = {"related_to_with_ve": 0, "related_to_without_ve": 0, "other_with_ve": 0, "other_without_ve": 0}
    for t, ve, n in rows:
        key = ("related_to" if t == "RELATED_TO" else "other") + ("_with_ve" if ve else "_without_ve")
        out[key] += n
    return out


# ── ③ source_article_no ─────────────────────────────────────────────────────
def tally_article_scope(citations_by_doc: dict[str, list[Any]]) -> dict[str, int]:
    """citations_by_doc：source_doc_id → 該文件各引用的 article_no 清單（None／空字串＝無）。

    判定在**文件層**（不使用哨兵字串）：文件內任一引用有條號＝該文件適用條號；
    有值＝已知；無值且文件適用＝未知；無值且整份文件都沒有條號＝不適用。
    """
    out = {"known": 0, "not_applicable": 0, "unknown": 0}
    for cits in citations_by_doc.values():
        doc_applicable = any(a not in (None, "") for a in cits)
        for a in cits:
            if a not in (None, ""):
                out["known"] += 1
            elif doc_applicable:
                out["unknown"] += 1
            else:
                out["not_applicable"] += 1
    return out


def citations_by_doc(edge_citation_lists: Iterable[list[dict]]) -> dict[str, list[Any]]:
    by_doc: dict[str, list[Any]] = {}
    for cits in edge_citation_lists:
        for c in cits:
            by_doc.setdefault(c.get("source_doc_id") or "None", []).append(c.get("article_no"))
    return by_doc


# ── ④ 空欄位 ─────────────────────────────────────────────────────────────────
def classify_fact_empties(empty_subject: bool, empty_object: bool, empty_verb: bool) -> str:
    """complete／unknown_determinate（空受詞且空 verb，可唯讀確定）／pending_needs_human_or_llm（其餘有空欄位者）。"""
    if empty_object and empty_verb:
        return "unknown_determinate"
    if empty_subject or empty_object or empty_verb:
        return "pending_needs_human_or_llm"
    return "complete"


def tally_fact_empties(rows: Iterable[tuple[bool, bool, bool, int]]) -> dict[str, Any]:
    """rows＝(空主詞, 空受詞, 空 verb, Fact 數)。"""
    combos: Counter[str] = Counter()
    cats: Counter[str] = Counter()
    single = Counter()
    for es, eo, ev, n in rows:
        combos[f"subject={int(es)},object={int(eo)},verb={int(ev)}"] += n
        cats[classify_fact_empties(es, eo, ev)] += n
        single["empty_subject"] += n if es else 0
        single["empty_object"] += n if eo else 0
        single["empty_verb"] += n if ev else 0
    for k in ("complete", "unknown_determinate", "pending_needs_human_or_llm"):
        cats.setdefault(k, 0)
    return {"combos": dict(sorted(combos.items())), "categories": dict(cats), "single_counts": dict(single),
            "facts_total": sum(cats.values()), "facts_with_any_empty": cats["unknown_determinate"] + cats["pending_needs_human_or_llm"]}


# ── 基準線 ───────────────────────────────────────────────────────────────────
def _pct(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def baseline_row(population: int, already_marked: int, derivable: int, needs_human_or_llm: int, *, note: str = "") -> dict[str, Any]:
    """基準線一列。三者互斥且加總＝母體（不變量，由呼叫端與測試保證）。"""
    return {
        "population": population,
        "already_explicitly_marked": already_marked, "already_explicitly_marked_share": _pct(already_marked, population),
        "derivable_read_only": derivable, "derivable_read_only_share": _pct(derivable, population),
        "needs_human_or_llm": needs_human_or_llm, "needs_human_or_llm_share": _pct(needs_human_or_llm, population),
        "partition_ok": already_marked + derivable + needs_human_or_llm == population,
        "note": note,
    }


def build_baseline(entity_cat: dict[str, int], rel: dict[str, int], article: dict[str, int], empties: dict[str, Any],
                   marked: dict[str, int]) -> dict[str, Any]:
    """marked：各對象「資料中已存在的明確標示」件數（本 KG 實測應全為 0，見 `find_marker_keys`）。"""
    e_total = sum(entity_cat.values())
    e_der = entity_cat["standard"] + entity_cat["standard_with_concept"] + entity_cat["empty"] + entity_cat["outside_raw"]
    r_total = sum(rel.values())
    r_der = rel["declared_non_related_to"]
    a_total = sum(article.values())
    f_any = empties["facts_with_any_empty"]
    f_der = empties["categories"]["unknown_determinate"]
    return {
        "entity_type": baseline_row(e_total, marked.get("entity_type", 0), e_der, entity_cat["concept_only"],
                                    note="嚴格算法：「概念」的預設／真實含意無法唯讀判定，列入需人工／LLM；A／B 兩種假設算法見 entity_type_marks。"
                                         "outside_raw 依報告201 §1.2 對應『尚未處理』，但 §1.1 指出無法分辨『尚未對應』與『已判定非 schema.org』。"),
        "relation_type": baseline_row(r_total, marked.get("relation_type", 0), r_der, r_total - r_der,
                                      note="嚴格算法：僅非 RELATED_TO 可確定；RELATED_TO 來源不明（報告201 §2.1）。R-D 假設算法見 rel_type_marks。"),
        "source_article_no": baseline_row(a_total, marked.get("source_article_no", 0), a_total, 0,
                                          note="母體＝邊上的引用（citations_json）；文件層判定，本 KG 100% 可唯讀確定。"),
        "empty_fields_among_facts_with_any_empty": baseline_row(f_any, marked.get("empty_fields", 0), f_der, f_any - f_der,
                                                                note="母體＝至少有一個空欄位（主詞／受詞／verb）的 Fact；完整 Fact 不需標示。"
                                                                     "唯讀可確定＝空受詞且空 verb；其餘需人工／LLM 區分『不適用』與『未知』。"),
    }


def find_marker_keys(key_rows: Iterable[tuple[str, str, int]]) -> list[dict[str, Any]]:
    """從（對象, 屬性鍵, 數量）清單挑出名稱像「標示欄位」的候選鍵（粗篩，由人判讀）。"""
    return [{"owner": o, "key": k, "n": n} for o, k, n in key_rows if _MARKER_KEY_RE.search(k)]


# ── 唯讀收集（連 Neo4j；僅 main 使用）────────────────────────────────────────────
def collect(driver: Any, kg: str, core_types: set[str], ext_json: Path) -> dict[str, Any]:
    r = ReadOnlyRunner(driver)
    res: dict[str, Any] = {"kg_id": kg}
    res["before"] = totals(r, kg, "before")
    if res["before"] != EXPECTED_TOTALS:
        raise SystemExit(f"資料量與預期不符，停止：{res['before']}")

    core_lookup = {normalize_type_key(k): k for k in core_types}
    ext_payload = json.loads(ext_json.read_text(encoding="utf-8"))
    ext_lookup = {normalize_type_key(t["label"]): t["id"] for t in ext_payload.get("types", [])}
    res["type_tables"] = {"core_size": len(core_lookup), "extended_size": len(ext_lookup)}

    # 標示欄位是否已存在（Entity／Fact／邊／Chunk／LawArticle 屬性鍵）
    node_keys = [(x["l"], x["key"], x["n"]) for x in r.run("屬性鍵（節點）", "MATCH (n {kg_id: $k}) UNWIND keys(n) AS key RETURN labels(n)[0] AS l, key, count(*) AS n ORDER BY l, n DESC", k=kg)]
    edge_keys = [(x["t"], x["key"], x["n"]) for x in r.run("屬性鍵（邊）", "MATCH ()-[r {kg_id: $k}]->() UNWIND keys(r) AS key RETURN type(r) AS t, key, count(*) AS n ORDER BY t, n DESC", k=kg)]
    res["property_keys_nodes"] = node_keys
    res["property_keys_edges_top"] = sorted(edge_keys, key=lambda x: -x[2])[:60]
    res["marker_key_candidates"] = find_marker_keys(node_keys + edge_keys)

    # ① 實體型別（以原字串聚合）
    type_rows = [(x["t"], x["n"]) for x in r.run("① 實體 type 分布", "MATCH (e:Entity {kg_id: $k}) RETURN e.type AS t, count(*) AS n", k=kg)]
    res["entity_type_raw_distinct"] = len(type_rows)
    res["entity_type_categories"] = tally_entity_types(type_rows, core_lookup, ext_lookup)
    res["entity_type_marks"] = entity_type_marks(res["entity_type_categories"])
    res["entity_empty_name_type"] = r.run("① 空名實體的 type", "MATCH (e:Entity {kg_id: $k}) WHERE trim(coalesce(e.name, '')) = '' RETURN e.type AS type, count(*) AS n", k=kg)
    res["entity_concept_only_top_check"] = r.run("① 「概念」精確字串實體數", "MATCH (e:Entity {kg_id: $k}) WHERE e.type = '概念' RETURN count(*) AS v", k=kg)[0]["v"]

    # ② 關係型別
    rel_rows = [(x["t"], x["ev"], x["n"]) for x in r.run("② Fact rel_type × verb 是否空", "MATCH (f:Fact {kg_id: $k}) RETURN f.rel_type AS t, trim(coalesce(f.verb, '')) = '' AS ev, count(*) AS n", k=kg)]
    res["rel_type_tally"] = tally_rel_types(rel_rows)
    res["rel_type_marks"] = rel_type_marks(res["rel_type_tally"])
    ve_rows = [(x["t"], x["ve"], x["n"]) for x in r.run("② 事實邊 × verb_embedding 有無", "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.citations_json IS NOT NULL RETURN type(r) AS t, r.verb_embedding IS NOT NULL AS ve, count(*) AS n", k=kg)]
    res["edge_verb_embedding_distribution"] = tally_edge_verb_embedding(ve_rows)
    res["edge_verb_embedding_note"] = "僅描述分布；verb_embedding 不是『兜底』專屬標記（報告201 §2.1：RELATED_TO 且有 verb 時一律寫入）。"

    # ③ source_article_no（引用層，文件層判定）
    edges = r.run("③ 事實邊引用", "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.citations_json IS NOT NULL RETURN r.citations_json AS c", k=kg)
    by_doc = citations_by_doc(parse_citations(e["c"]) for e in edges)
    res["article_scope"] = tally_article_scope(by_doc)
    res["article_docs"] = {"docs": len(by_doc), "docs_with_any_article_no": sum(1 for v in by_doc.values() if any(a not in (None, "") for a in v))}
    res["fact_supported_by_target_labels"] = [(x["l"], x["n"]) for x in r.run("③ Fact SUPPORTED_BY 目標標籤", "MATCH (f:Fact {kg_id: $k})-[:SUPPORTED_BY]->(t) RETURN labels(t)[0] AS l, count(*) AS n ORDER BY n DESC", k=kg)]
    res["document_nodes"] = r.run("③ Document 節點數與 record_type", "MATCH (d:Document {kg_id: $k}) RETURN d.record_type AS rt, count(*) AS n", k=kg)

    # ④ 空欄位
    em_rows = [(x["es"], x["eo"], x["ev"], x["n"]) for x in r.run("④ Fact 空主詞×空受詞×空 verb", "MATCH (f:Fact {kg_id: $k}) RETURN trim(coalesce(f.subject, '')) = '' AS es, trim(coalesce(f.object, '')) = '' AS eo, trim(coalesce(f.verb, '')) = '' AS ev, count(*) AS n", k=kg)]
    res["fact_empties"] = tally_fact_empties(em_rows)
    res["fact_null_fields"] = r.run("④ Fact 欄位為 NULL（非空字串）的數量", "MATCH (f:Fact {kg_id: $k}) RETURN sum(CASE WHEN f.subject IS NULL THEN 1 ELSE 0 END) AS null_subject, sum(CASE WHEN f.object IS NULL THEN 1 ELSE 0 END) AS null_object, sum(CASE WHEN f.verb IS NULL THEN 1 ELSE 0 END) AS null_verb", k=kg)[0]

    res["baseline"] = build_baseline(res["entity_type_categories"], res["rel_type_tally"], res["article_scope"], res["fact_empties"],
                                     {"entity_type": 0, "relation_type": 0, "source_article_no": 0, "empty_fields": 0})
    res["baseline_marked_basis"] = "已有明確標示件數＝0 的依據：marker_key_candidates 為空（資料中無 status／origin／scope 類屬性鍵）；若非空須人工判讀後再填。"

    res["after"] = totals(r, kg, "after")
    res["totals_identical"] = res["before"] == res["after"]
    res["cypher_log"] = r.log
    return res


def read_env_value(env_file: Path, key: str) -> str | None:
    """從 .env 檔讀單一值（不改 os.environ）。"""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        m = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--kg-id", default=KG_ID_DEFAULT)
    ap.add_argument("--uri", default=BOLT_URI_DEFAULT)
    ap.add_argument("--user", default="neo4j")
    ap.add_argument("--password", default=None)
    ap.add_argument("--env-file", type=Path, default=None, help="從該 .env 讀 NEO4J_PASSWORD（不改 os.environ）")
    a = ap.parse_args(argv)
    password = a.password or (read_env_value(a.env_file, "NEO4J_PASSWORD") if a.env_file else None)
    if not password:
        raise SystemExit("需要 --password 或 --env-file")
    from neo4j import GraphDatabase  # noqa: PLC0415
    from core.constants import ENTITY_TYPES  # noqa: PLC0415

    driver = GraphDatabase.driver(a.uri, auth=(a.user, password))
    try:
        res = collect(driver, a.kg_id, set(ENTITY_TYPES), _REPO / "data" / "schema_org_entity_types.json")
    finally:
        driver.close()
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("totals identical:", res["totals_identical"], res["before"], res["after"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
