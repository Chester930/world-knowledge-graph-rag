"""語意層「圖譜保證」不變量的唯讀實測（報告195 F2／報告196 F1 清單的可檢查項）。

**唯讀**：只對 Neo4j 執行 `MATCH … RETURN`／`CALL db.*`／`SHOW CONSTRAINTS|INDEXES`，
session 為 `default_access_mode=READ`，且每條 Cypher 先經 `assert_read_only()` 檢查
（含寫入關鍵字即中止）。**不呼叫任何 LLM／embedding**。只輸出數字，不判斷是否「違反」簡報。

匯入本模組**不得**改 `os.environ`、不得連線、不得匯入 `core`／`services`（`core.constants` 於
`main()` 內延遲匯入）——對應 B1／C3／D2 的教訓，見 tests/scripts/test_semantic_layer_invariants.py。

用法（需 Neo4j 唯讀連線）：
    python scripts/analysis/semantic_layer_invariants.py --out <result.json>
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

KG_ID_DEFAULT = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG_RUNTIME_DEFAULT = Path("D:/Users/666/Desktop/kg-runtime")
BOLT_URI_DEFAULT = "bolt://localhost:17990"
EXPECTED_TOTALS = {"nodes": 57451, "rels": 137873, "facts": 16826, "entities": 12296}

# ── 唯讀檢查 ────────────────────────────────────────────────────────────────
# 最終白名單（報告195 F2 防護的細化，規劃對話裁定）：
#   1. 以 MATCH／UNWIND 開頭的唯讀查詢；
#   2. `SHOW CONSTRAINTS`、`SHOW INDEXES`（唯讀內省）；
#   3. `CALL` 僅限 db.labels()／db.relationshipTypes()／db.propertyKeys()（不放行 `db.*` 一般性呼叫：
#      部分 db.* 程序會寫入 schema，例如 db.create.*、db.createLabel／createProperty、全文索引建立類）。
# 真正的保護仍是 `default_access_mode=READ` 的 session；此關鍵字攔截是第二道，兩者都保留。
_FORBID = re.compile(
    r"\b(?:CREATE|MERGE|SET|DELETE|DETACH|DROP|REMOVE|LOAD|FOREACH|INDEX\s+ON)\b|apoc\.",
    re.IGNORECASE,
)
_CALL_WORD = re.compile(r"\bCALL\b", re.IGNORECASE)
_CALL_WHITELIST = re.compile(r"\s*CALL\s+db\.(?:labels|relationshipTypes|propertyKeys)\s*\(\s*\)", re.IGNORECASE)
_ALLOWED_START = re.compile(r"\s*(?:MATCH\b|UNWIND\b|SHOW\s+(?:CONSTRAINTS|INDEXES)\b)", re.IGNORECASE)


def assert_read_only(cypher: str) -> None:
    """含寫入關鍵字、非白名單的 CALL、或不以白名單開頭字樣起頭的 Cypher 一律拒絕。"""
    if _FORBID.search(cypher):
        raise ValueError(f"拒絕：Cypher 含寫入關鍵字：{cypher[:80]}")
    if _CALL_WORD.search(cypher):
        if not _CALL_WHITELIST.match(cypher) or len(_CALL_WORD.findall(cypher)) != 1:
            raise ValueError(f"拒絕：CALL 不在白名單：{cypher[:80]}")
        return
    if not _ALLOWED_START.match(cypher):
        raise ValueError(f"拒絕：Cypher 不以白名單開頭字樣起頭：{cypher[:80]}")



# ── 純運算（可單元測試，不連 Neo4j）────────────────────────────────────────────
def percentile(sorted_values: list[float], p: float) -> float | None:
    """nearest-rank：排序後第 round(p*(n-1)) 個。"""
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1))))]


def describe(values: Iterable[float]) -> dict[str, Any]:
    v = sorted(values)
    if not v:
        return {"n": 0}
    return {
        "n": len(v), "min": v[0], "median": statistics.median(v), "p90": percentile(v, 0.9),
        "max": v[-1], "mean": round(sum(v) / len(v), 3), "share_eq_1": round(sum(1 for x in v if x == 1) / len(v), 4),
    }


def parse_citations(raw: str | None) -> list[dict]:
    """`citations_json` → 引用清單；空值或格式錯誤回傳 []（並由呼叫端另計）。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def citation_key_stats(edges_citations: Iterable[list[dict]]) -> dict[str, Any]:
    """所有引用的鍵集合與各鍵「非空」比例；另統計引用總數。"""
    total = 0
    present: Counter[str] = Counter()
    non_null: Counter[str] = Counter()
    for cits in edges_citations:
        for c in cits:
            total += 1
            for k, v in c.items():
                present[k] += 1
                if v is not None:
                    non_null[k] += 1
    return {
        "citations": total,
        "keys": {k: {"present": present[k], "non_null": non_null[k]} for k in sorted(present)},
    }


def distinct_verbs(cits: list[dict]) -> list[str]:
    seen: list[str] = []
    for c in cits:
        v = (c.get("verb") or "").strip()
        if v and v not in seen:
            seen.append(v)
    return seen


_NEG_CUES = ("不得", "不應", "不可", "禁止", "不予", "毋", "不准")
_POS_CUES = ("得", "應", "須", "可", "准")


def verb_polarity(verb: str) -> str:
    """保守啟發式：含否定／禁止樣式→neg；含「得／應／須／可／准」且無否定→pos；其餘 neutral。"""
    if any(c in verb for c in _NEG_CUES):
        return "neg"
    if any(c in verb for c in _POS_CUES):
        return "pos"
    return "neutral"


def has_opposing_verbs(verbs: list[str]) -> bool:
    pols = {verb_polarity(v) for v in verbs}
    return "neg" in pols and "pos" in pols


def normalize_entity_name(name: str) -> str:
    """G3-02a：去全半形差異、空白、大小寫；不做簡繁轉換（只做字面正規化）。"""
    s = unicodedata.normalize("NFKC", name or "")
    return re.sub(r"\s+", "", s).lower()


def aliases_stats(rows: Iterable[tuple[str, list[str] | None]]) -> dict[str, int]:
    out: Counter[str] = Counter({k: 0 for k in (
        "entities", "aliases_null", "aliases_present", "aliases_empty_list", "name_not_in_aliases", "aliases_has_duplicates")})
    for name, aliases in rows:
        out["entities"] += 1
        if aliases is None:
            out["aliases_null"] += 1
            continue
        out["aliases_present"] += 1
        if len(aliases) == 0:
            out["aliases_empty_list"] += 1
        if name not in aliases:
            out["name_not_in_aliases"] += 1
        if len(set(aliases)) != len(aliases):
            out["aliases_has_duplicates"] += 1
    return dict(out)


def normalize_type_key(value: str) -> str:
    """與 services/extraction/prompt.py::_normalize_type_key 相同的比對鍵（本模組自行實作以免匯入 services）。"""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def classify_type_tokens(
    raw_type: str | None, core_lookup: dict[str, str], ext_lookup: dict[str, str]
) -> list[tuple[str, str]]:
    """把一個實體的 `type` 字串（可逗號多值）拆成 [(token, 類別)]；類別：core／extended／outside。空值回傳 []。"""
    if raw_type is None or not str(raw_type).strip():
        return []
    out = []
    for token in str(raw_type).split(","):
        token = token.strip()
        if not token:
            continue
        key = normalize_type_key(token)
        if key in core_lookup:
            out.append((token, "core"))
        elif key in ext_lookup:
            out.append((token, "extended"))
        else:
            out.append((token, "outside"))
    return out


_NUM = r"(?:[0-9０-９]+(?:\.[0-9]+)?|[零〇一二三四五六七八九十百千萬兩]+)"
_UNIT = r"(?:元|日|天|小時|分鐘|人|歲|月|年|週|周|%|％|倍|公斤|公分|公尺|公里|公頃|次|件|筆|組|名|位|成|分之)"
_RE_QUANTITY = re.compile(_NUM + _UNIT)
_RE_COMPARATOR = re.compile(r"以上|以下|未滿|超過|不得超過|至少|至多|不足|低於|高於|未達")
_RE_ORDINAL = re.compile(r"第[0-9０-９零〇一二三四五六七八九十百千萬兩]+[條項款目章節編類級等種]|[甲乙丙丁戊己庚辛壬癸]類")
_RE_GRADE = re.compile(r"[0-9０-９一二三四五六七八九十甲乙丙丁]+(?:級|等|類|型)")


def value_flags(name: str) -> dict[str, bool]:
    """V-01：值節點的操作型識別樣式（〔提案〕；可能誤判，F2 會另給樣本）。"""
    n = name or ""
    flags = {
        "quantity": bool(_RE_QUANTITY.search(n)),
        "comparator": bool(_RE_COMPARATOR.search(n)),
        "ordinal": bool(_RE_ORDINAL.search(n)),
        "grade": bool(_RE_GRADE.search(n)),
    }
    flags["any"] = any(flags.values())
    return flags


def degrees_from_edges(edges: Iterable[tuple[str, str]]) -> Counter[str]:
    """事實邊（subject, object）→ 每個實體名稱的度數（入＋出；自環計 2）。"""
    deg: Counter[str] = Counter()
    for s, o in edges:
        deg[s] += 1
        deg[o] += 1
    return deg


def rel_type_vocab_check(counts: dict[str, int], declared: set[str]) -> dict[str, Any]:
    outside = {t: c for t, c in counts.items() if t not in declared}
    return {"total": sum(counts.values()), "outside_declared": outside, "outside_count": sum(outside.values())}


# ── 唯讀查詢收集（連 Neo4j；僅 main 路徑使用）──────────────────────────────────
class ReadOnlyRunner:
    def __init__(self, driver: Any):
        self.driver = driver
        self.log: list[dict] = []

    def run(self, label: str, cypher: str, **params: Any) -> list[dict]:
        assert_read_only(cypher)
        with self.driver.session(default_access_mode="READ") as s:
            rows = [r.data() for r in s.run(cypher, **params)]
        self.log.append({"label": label, "cypher": " ".join(cypher.split()), "rows": len(rows)})
        return rows


def totals(r: ReadOnlyRunner, kg: str, tag: str) -> dict[str, int]:
    return {
        "nodes": r.run(f"{tag}:總節點", "MATCH (n) RETURN count(n) AS v")[0]["v"],
        "rels": r.run(f"{tag}:總關係", "MATCH ()-[r]->() RETURN count(r) AS v")[0]["v"],
        "facts": r.run(f"{tag}:Fact", "MATCH (f:Fact {kg_id: $k}) RETURN count(f) AS v", k=kg)[0]["v"],
        "entities": r.run(f"{tag}:Entity", "MATCH (e:Entity {kg_id: $k}) RETURN count(e) AS v", k=kg)[0]["v"],
    }


def collect(driver: Any, kg: str, kg_dir: Path, core_types: set[str], declared_rel: set[str], ext_json: Path) -> dict[str, Any]:
    from core.constants import DOCUMENT_ID_NAMESPACE  # 延遲匯入（僅 main 路徑）

    r = ReadOnlyRunner(driver)
    res: dict[str, Any] = {}
    res["before"] = totals(r, kg, "before")
    if res["before"] != EXPECTED_TOTALS:
        raise SystemExit(f"資料量與預期不符，停止：{res['before']}")

    # schema 內省
    res["labels"] = sorted(x["label"] for x in r.run("labels", "CALL db.labels() YIELD label RETURN label"))
    res["rel_types"] = sorted(x["relationshipType"] for x in r.run("relationshipTypes", "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"))
    res["property_keys"] = sorted(x["propertyKey"] for x in r.run("propertyKeys", "CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey"))
    res["constraints"] = [{k: v for k, v in x.items() if k in ("name", "type", "entityType", "labelsOrTypes", "properties")} for x in r.run("SHOW CONSTRAINTS", "SHOW CONSTRAINTS")]
    res["indexes"] = [{k: v for k, v in x.items() if k in ("name", "type", "entityType", "labelsOrTypes", "properties")} for x in r.run("SHOW INDEXES", "SHOW INDEXES")]

    # G1 / G6-02 / G8-03
    res["fact_total"] = res["before"]["facts"]
    res["g1_01_fact_missing_source"] = r.run("G1-01", "MATCH (f:Fact {kg_id: $k}) WHERE f.source_doc_id IS NULL OR f.source_svo_chunk_index IS NULL RETURN count(f) AS v", k=kg)[0]["v"]
    res["g1_02_fact_no_supported_by"] = r.run("G1-02", "MATCH (f:Fact {kg_id: $k}) WHERE NOT (f)-[:SUPPORTED_BY]->(:Chunk) RETURN count(f) AS v", k=kg)[0]["v"]
    res["g1_02b_fact_no_supported_by_any_target"] = r.run("G1-02b 完全沒有 SUPPORTED_BY 的 Fact", "MATCH (f:Fact {kg_id: $k}) WHERE NOT (f)-[:SUPPORTED_BY]->() RETURN count(f) AS v", k=kg)[0]["v"]
    res["g1_02c_supported_by_target_labels"] = [(x["l"], x["n"]) for x in r.run("G1-02c SUPPORTED_BY 目標節點標籤分布", "MATCH (f:Fact {kg_id: $k})-[:SUPPORTED_BY]->(t) RETURN labels(t) AS l, count(*) AS n ORDER BY n DESC", k=kg)]
    res["g1_04_entity_no_has_entity"] = r.run("G1-04", "MATCH (e:Entity {kg_id: $k}) WHERE NOT ()-[:HAS_ENTITY]->(e) RETURN count(e) AS v", k=kg)[0]["v"]
    chunk_docs = [x["d"] for x in r.run("G1-05", "MATCH (c:Chunk {kg_id: $k}) RETURN DISTINCT c.source_doc_id AS d", k=kg)]
    folders = sorted(p.name for p in (kg_dir / kg).iterdir() if p.is_dir())
    fid = {str(uuid.uuid5(DOCUMENT_ID_NAMESPACE, f)): f for f in folders}
    res["g1_05"] = {"chunk_distinct_source_doc_ids": len(chunk_docs), "folders": len(folders),
                    "unmapped_doc_ids": [d for d in chunk_docs if d not in fid], "folders_without_chunks": [f for f in folders if not any(fid.get(d) == f for d in chunk_docs)]}
    res["fact_keys"] = {x["key"]: x["n"] for x in r.run("Fact 屬性鍵", "MATCH (f:Fact {kg_id: $k}) UNWIND keys(f) AS key RETURN key, count(*) AS n ORDER BY n DESC", k=kg)}
    res["chunk_keys"] = {x["key"]: x["n"] for x in r.run("Chunk 屬性鍵", "MATCH (c:Chunk {kg_id: $k}) UNWIND keys(c) AS key RETURN key, count(*) AS n ORDER BY n DESC", k=kg)}
    res["entity_keys"] = {x["key"]: x["n"] for x in r.run("Entity 屬性鍵", "MATCH (e:Entity {kg_id: $k}) UNWIND keys(e) AS key RETURN key, count(*) AS n ORDER BY n DESC", k=kg)}
    res["fact_confidence"] = {str(x["c"]): x["n"] for x in r.run("Fact confidence 分布", "MATCH (f:Fact {kg_id: $k}) RETURN f.confidence AS c, count(*) AS n ORDER BY c", k=kg)}
    res["fact_rel_type"] = {x["t"]: x["n"] for x in r.run("Fact rel_type 分布", "MATCH (f:Fact {kg_id: $k}) RETURN f.rel_type AS t, count(*) AS n ORDER BY n DESC", k=kg)}
    res["related_to_verb_top20"] = [(x["v"], x["n"]) for x in r.run("RELATED_TO Fact 的 verb 前 20", "MATCH (f:Fact {kg_id: $k, rel_type: 'RELATED_TO'}) RETURN f.verb AS v, count(*) AS n ORDER BY n DESC, v LIMIT 20", k=kg)]
    res["endpoint_types_top"] = [(x["t"], x["st"], x["ot"], x["n"]) for x in r.run("G6-03 端點型別組合（描述）", "MATCH (f:Fact {kg_id: $k}) MATCH (f)-[:HAS_SUBJECT]->(s) MATCH (f)-[:HAS_OBJECT]->(o) RETURN f.rel_type AS t, s.type AS st, o.type AS ot, count(*) AS n ORDER BY n DESC LIMIT 60", k=kg)]

    # 實體
    ents = r.run("全部 Entity", "MATCH (e:Entity {kg_id: $k}) RETURN e.name AS name, e.type AS type, e.aliases AS aliases, keys(e) AS ks", k=kg)
    res["entity_count"] = len(ents)
    res["g3_03_aliases"] = aliases_stats((e["name"], e["aliases"]) for e in ents)
    groups: dict[str, list] = defaultdict(list)
    for e in ents:
        groups[normalize_entity_name(e["name"])].append((e["name"], e["type"]))
    coll = {k: v for k, v in groups.items() if len(v) > 1}
    res["g3_02a_normalized_name_collisions"] = {"groups": len(coll), "entities": sum(len(v) for v in coll.values()),
                                               "groups_with_different_types": sum(1 for v in coll.values() if len({t for _, t in v}) > 1),
                                               "samples": [v for v in list(coll.values())[:20]]}
    res["g3_02b_type"] = {"empty": sum(1 for e in ents if not (e["type"] or "").strip()), "multi_valued": sum(1 for e in ents if "," in (e["type"] or ""))}

    # G9 型別標準化
    core_lookup = {normalize_type_key(k): k for k in core_types}
    ext_payload = json.loads(ext_json.read_text(encoding="utf-8"))
    ext_lookup = {normalize_type_key(t["label"]): t["id"] for t in ext_payload.get("types", [])}
    tok_entities: Counter[tuple[str, str]] = Counter()
    ent_cat = Counter()
    for e in ents:
        toks = classify_type_tokens(e["type"], core_lookup, ext_lookup)
        if not toks:
            ent_cat["empty"] += 1
            continue
        cats = {c for _, c in toks}
        ent_cat["has_outside" if "outside" in cats else ("all_standard")] += 1
        for t, c in set(toks):
            tok_entities[(t, c)] += 1
    by_cat = Counter()
    for (t, c), n in tok_entities.items():
        by_cat[c] += n
    res["g9_01"] = {"core_size": len(core_types), "extended_size": len(ext_lookup), "entities_by_category": dict(ent_cat),
                    "type_token_entity_counts_by_category": dict(by_cat),
                    "distinct_tokens_by_category": dict(Counter(c for (_, c) in tok_entities))}
    res["g9_02_outside_top30"] = [(t, n) for (t, c), n in sorted(tok_entities.items(), key=lambda kv: -kv[1]) if c == "outside"][:30]

    # 事實邊
    edges = r.run("全部事實邊", "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.citations_json IS NOT NULL RETURN type(r) AS t, s.name AS s, o.name AS o, r.citations_json AS c, r.confidence AS conf, r.natural_text IS NOT NULL AS nt, r.verb_embedding IS NOT NULL AS ve, keys(r) AS ks", k=kg)
    res["edge_count"] = len(edges)
    res["edge_property_keys"] = dict(Counter(k for e in edges for k in e["ks"]))
    type_counts = Counter(e["t"] for e in edges)
    res["g4_01_rel_vocab"] = rel_type_vocab_check(dict(type_counts), declared_rel)
    res["edge_type_counts_top10"] = type_counts.most_common(10)
    res["g4_02_edge_related_to"] = {"related_to": type_counts.get("RELATED_TO", 0), "edges": len(edges)}
    res["g4_03_related_to_edges_with_verb_embedding"] = {"related_to_edges": type_counts.get("RELATED_TO", 0),
                                                        "with_verb_embedding": sum(1 for e in edges if e["t"] == "RELATED_TO" and e["ve"])}
    res["g2_02_natural_text"] = {"edges": len(edges), "with_natural_text": sum(1 for e in edges if e["nt"])}
    edge_cits = [parse_citations(e["c"]) for e in edges]
    res["citation_json_unparsable_or_empty_edges"] = sum(1 for c in edge_cits if not c)
    res["g1_03_g2_01_g8_01_citation_keys"] = citation_key_stats(edge_cits)
    res["g8_02_edge_confidence"] = {str(k): v for k, v in sorted(Counter(e["conf"] for e in edges).items(), key=lambda kv: str(kv[0]))}
    res["g8_02_confidence_python_types"] = dict(Counter(type(e["conf"]).__name__ for e in edges))
    n_cit = Counter(len(c) for c in edge_cits)
    res["g7_02_citations_per_edge"] = {"distribution": {str(k): v for k, v in sorted(n_cit.items())[:12]}, "edges_ge2": sum(v for k, v in n_cit.items() if k >= 2)}
    multi_doc = sum(1 for c in edge_cits if len({x.get("source_doc_id") for x in c if x.get("source_doc_id")}) >= 2)
    res["g7_02_edges_with_ge2_distinct_docs"] = multi_doc
    dv = [len(distinct_verbs(c)) for c in edge_cits]
    res["g4_04_distinct_verbs_per_edge"] = {"distribution": {str(k): v for k, v in sorted(Counter(dv).items())[:12]}, "edges_ge2_verbs": sum(1 for x in dv if x >= 2)}
    opp = [(e["s"], e["t"], e["o"], distinct_verbs(c), len({x.get("source_doc_id") for x in c if x.get("source_doc_id")}))
           for e, c in zip(edges, edge_cits) if has_opposing_verbs(distinct_verbs(c))]
    res["g5_04_g7_04_opposing_verb_edges"] = {"count": len(opp), "with_ge2_docs": sum(1 for x in opp if x[4] >= 2), "samples": opp[:20]}
    art_by_doc: dict[str, list] = defaultdict(list)
    for cits in edge_cits:
        for c in cits:
            art_by_doc[c.get("source_doc_id") or "None"].append(c.get("article_no"))
    docs_with_article = {d for d, v in art_by_doc.items() if any(a is not None for a in v)}
    res["u01_article_no"] = {
        "citations": sum(len(v) for v in art_by_doc.values()),
        "null_total": sum(1 for v in art_by_doc.values() for a in v if a is None),
        "docs_with_any_article_no": len(docs_with_article), "docs_without_any_article_no": len(art_by_doc) - len(docs_with_article),
        "null_in_docs_with_article_no": sum(1 for d in docs_with_article for a in art_by_doc[d] if a is None),
        "citations_in_docs_with_article_no": sum(len(art_by_doc[d]) for d in docs_with_article),
        "null_in_docs_without_article_no": sum(1 for d, v in art_by_doc.items() if d not in docs_with_article for a in v if a is None),
        "citations_in_docs_without_article_no": sum(len(v) for d, v in art_by_doc.items() if d not in docs_with_article),
    }
    # G5-03 / G7-03 （DB 端與 Python 端各算一次互相印證）
    res["g5_03_parallel_edges_groups"] = r.run("G5-03 同（主詞,關係,受詞）多條邊的組數", "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.citations_json IS NOT NULL WITH s, o, type(r) AS t, count(r) AS c WHERE c > 1 RETURN count(*) AS v", k=kg)[0]["v"]
    pair_types: dict[tuple[str, str], set] = defaultdict(set)
    for e in edges:
        pair_types[(e["s"], e["o"])].add(e["t"])
    multi_type = {k: v for k, v in pair_types.items() if len(v) > 1}
    res["g7_03_pairs_with_multiple_rel_types"] = {"pairs": len(multi_type),
                                                  "combo_top10": Counter(tuple(sorted(v)) for v in multi_type.values()).most_common(10)}
    res["g7_03_cypher_pairs"] = r.run("G7-03 同（主詞,受詞）多關係型別的組數", "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.citations_json IS NOT NULL WITH s.name AS s, o.name AS o, collect(DISTINCT type(r)) AS ts WHERE size(ts) > 1 RETURN count(*) AS v", k=kg)[0]["v"]

    # V-01 / V-02 值節點專項
    deg = degrees_from_edges((e["s"], e["o"]) for e in edges)
    docs_per = {x["name"]: x["docs"] for x in r.run("V-02 每個實體被幾個不同來源文件提及", "MATCH (c:Chunk {kg_id: $k})-[:HAS_ENTITY]->(e:Entity {kg_id: $k}) RETURN e.name AS name, count(DISTINCT c.source_doc_id) AS docs", k=kg)}
    groups_v: dict[str, list] = {"value": [], "non_value": []}
    flag_counts = Counter()
    samples: dict[str, list] = defaultdict(list)
    for e in ents:
        f = value_flags(e["name"])
        for k2, v2 in f.items():
            if v2 and k2 != "any":
                flag_counts[k2] += 1
                if len(samples[k2]) < 8:
                    samples[k2].append(e["name"])
        groups_v["value" if f["any"] else "non_value"].append(e["name"])
    def summarize(names: list[str]) -> dict:
        d = describe(deg.get(n, 0) for n in names)
        d["docs_ge2_share"] = round(sum(1 for n in names if docs_per.get(n, 0) >= 2) / len(names), 4) if names else None
        d["docs_median"] = statistics.median(docs_per.get(n, 0) for n in names) if names else None
        d["degree_zero"] = sum(1 for n in names if deg.get(n, 0) == 0)
        return d
    res["v01_v02"] = {"entities": len(ents), "value_nodes": len(groups_v["value"]), "value_share": round(len(groups_v["value"]) / len(ents), 4),
                      "flag_counts": dict(flag_counts), "samples": dict(samples),
                      "value_stats": summarize(groups_v["value"]), "non_value_stats": summarize(groups_v["non_value"]),
                      "degree_definition": "事實邊（r.citations_json IS NOT NULL）入＋出，自環計 2；不含 HAS_ENTITY／HAS_SUBJECT 等結構邊"}

    res["obs_empty_name_entities"] = r.run("OBS 空字串名稱的實體", "MATCH (e:Entity {kg_id: $k}) WHERE trim(e.name) = '' RETURN e.name AS name, e.type AS type", k=kg)
    res["obs_top_degree_entities"] = [(n, d) for n, d in deg.most_common(10)]
    res["obs_fact_empty_subject_object"] = r.run("OBS Fact 空主詞／空受詞／空 verb 數", "MATCH (f:Fact {kg_id: $k}) RETURN sum(CASE WHEN trim(f.subject) = '' THEN 1 ELSE 0 END) AS empty_subject, sum(CASE WHEN trim(f.object) = '' THEN 1 ELSE 0 END) AS empty_object, sum(CASE WHEN trim(f.verb) = '' THEN 1 ELSE 0 END) AS empty_verb", k=kg)[0]
    res["g8_03_g1_06_label_properties"] = {}
    for prop in ("content_hash", "created_at", "updated_at", "svo_processed_at", "effective_date", "update_date", "record_type", "source_url", "source_chunk_ids", "model", "provider"):
        res["g8_03_g1_06_label_properties"][prop] = [(x["l"], x["n"]) for x in r.run(f"屬性 {prop} 出現在哪些標籤", f"MATCH (n) WHERE n.{prop} IS NOT NULL RETURN labels(n) AS l, count(*) AS n ORDER BY n DESC")]
    res["obs_document_nodes"] = r.run("OBS Document 節點數與其屬性鍵", "MATCH (d:Document) UNWIND keys(d) AS key RETURN key, count(*) AS n ORDER BY n DESC")
    res["obs_document_nodes_kg"] = r.run("OBS 本 KG 的 Document 節點（content_hash／日期／record_type 覆蓋）", "MATCH (d:Document {kg_id: $k}) RETURN count(d) AS docs, count(d.content_hash) AS with_content_hash, count(d.update_date) AS with_update_date, count(d.effective_date) AS with_effective_date, collect(DISTINCT d.record_type) AS record_types", k=kg)[0]
    res["obs_document_nodes_all_kgs"] = [(x["k"], x["n"]) for x in r.run("OBS 各 KG 的 Document 節點數", "MATCH (d:Document) RETURN d.kg_id AS k, count(*) AS n ORDER BY n DESC")]
    res["obs_law_article_nodes_kg"] = r.run("OBS 本 KG 的 LawArticle 節點與其屬性鍵", "MATCH (a:LawArticle {kg_id: $k}) UNWIND keys(a) AS key RETURN key, count(*) AS n ORDER BY n DESC", k=kg)
    res["obs_chunk_to_document"] = [(x["t"], x["l"], x["n"]) for x in r.run("OBS Chunk 與 Document／LawArticle 的關係型別", "MATCH (c:Chunk {kg_id: $k})-[r]-(x) WHERE NOT x:Entity RETURN type(r) AS t, labels(x) AS l, count(*) AS n ORDER BY n DESC", k=kg)]
    short = [n for n in groups_v["value"] if len(n) <= 20]
    short_nv = [n for n in groups_v["non_value"] if len(n) <= 20]
    res["v01_v02_short_names_le20"] = {"value_nodes": len(short), "value_stats": summarize(short), "non_value_nodes": len(short_nv), "non_value_stats": summarize(short_nv)}

    # 檔案唯讀檢查：G1-06、G2-03、G7-01(b)、G8-04
    rec_keys: Counter[str] = Counter()
    rewritten_chunks = total_chunks = rewritten_sentences = total_sentences = 0
    idx_cache: dict[str, set[int]] = {}
    for f in folders:
        rp = kg_dir / kg / f / "_record.json"
        if rp.is_file():
            try:
                for k2 in json.loads(rp.read_text(encoding="utf-8")).keys():
                    rec_keys[k2] += 1
            except ValueError:
                pass
        ip = kg_dir / kg / f / "svo_index.json"
        j = json.loads(ip.read_text(encoding="utf-8"))
        idx_cache[f] = {c["index"] for c in j["chunks"]}
        for c in j["chunks"]:
            total_chunks += 1
            o = ["".join(s.split()) for s in c.get("original_sentences", [])]
            nrm = ["".join(s.split()) for s in c.get("normalized_sentences", [])]
            total_sentences += len(o)
            diff = sum(1 for a, b in zip(o, nrm) if a != b) + abs(len(o) - len(nrm))
            rewritten_sentences += diff
            rewritten_chunks += 1 if diff else 0
    res["g1_06_g7_01b_record_keys"] = dict(rec_keys)
    res["g2_03_rewrite"] = {"chunks": total_chunks, "chunks_with_rewritten_sentences": rewritten_chunks, "sentences": total_sentences, "rewritten_sentences": rewritten_sentences}
    # G8-04：Fact 與事實邊引用的 (source_doc_id, chunk index) 是否都能在 svo_index.json 找到（全量，非抽樣）
    pairs = r.run("G8-04 Fact 的 (source_doc_id, source_svo_chunk_index) 全部相異組合", "MATCH (f:Fact {kg_id: $k}) RETURN DISTINCT f.source_doc_id AS d, f.source_svo_chunk_index AS ci", k=kg)
    ok = sum(1 for x in pairs if fid.get(x["d"]) and x["ci"] in idx_cache.get(fid[x["d"]], set()))
    cit_pairs = {(c.get("source_doc_id"), c.get("source_svo_chunk_index")) for cits in edge_cits for c in cits}
    cit_ok = sum(1 for d_, ci in cit_pairs if fid.get(d_) and ci in idx_cache.get(fid[d_], set()))
    res["g8_04_traceback"] = {"fact_distinct_pairs": len(pairs), "fact_pairs_found_in_svo_index": ok,
                              "citation_distinct_pairs": len(cit_pairs), "citation_pairs_found_in_svo_index": cit_ok}

    res["after"] = totals(r, kg, "after")
    res["totals_identical"] = res["before"] == res["after"]
    res["cypher_log"] = r.log
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--kg-id", default=KG_ID_DEFAULT)
    ap.add_argument("--kg-runtime", type=Path, default=KG_RUNTIME_DEFAULT)
    ap.add_argument("--uri", default=BOLT_URI_DEFAULT)
    ap.add_argument("--user", default="neo4j")
    ap.add_argument("--password", required=True)
    a = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from neo4j import GraphDatabase  # noqa: PLC0415
    from core.constants import ENTITY_TYPES, SVO_REL_TYPES  # noqa: PLC0415

    driver = GraphDatabase.driver(a.uri, auth=(a.user, a.password))
    try:
        res = collect(driver, a.kg_id, a.kg_runtime, set(ENTITY_TYPES), set(SVO_REL_TYPES), repo / "data" / "schema_org_entity_types.json")
    finally:
        driver.close()
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("totals identical:", res["totals_identical"], res["before"], res["after"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
