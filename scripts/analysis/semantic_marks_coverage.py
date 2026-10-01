"""用報告212 L2 派生函式重算 Phase 0 覆蓋率（唯讀）。

本腳本只在 ``main()`` 內建立 Neo4j driver；匯入時不連線、不讀取環境變數、
不改 ``os.environ``。所有 Cypher 都交給報告195／207 的
``ReadOnlyRunner``，因此使用 ``default_access_mode="READ"`` 與同一個
``assert_read_only()`` 白名單。本腳本不寫入 KG、不呼叫 LLM／embedding。

輸出同時保留兩種口徑：

* 儲存層已有明確標示（本階段不寫入，預期為 0）；
* 派生函式能給出非「無法由現有資料判定」值的比例。這不是已落地的
  儲存標示。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.semantic_layer_invariants import (  # noqa: E402
    BOLT_URI_DEFAULT,
    EXPECTED_TOTALS,
    KG_ID_DEFAULT,
    ReadOnlyRunner,
    assert_read_only,
    parse_citations,
    totals,
)
from services.semantic_marks import (  # noqa: E402
    INDETERMINATE,
    MARKS,
    RESOLVED,
    classify_entity_type_value,
    mark_article_no,
    mark_citations_by_document,
    mark_entity_type,
    mark_fact_fields,
    mark_relation_type,
    normalize_type_key,
)

SCHEMES = ("strict", "A", "B")
PHASE0_RAW_DEFAULT = _REPO / "docs" / "報告" / "208_K2_phase0_raw結果.json"
EXT_TYPES_DEFAULT = _REPO / "data" / "schema_org_entity_types.json"
_MARKER_KEY_RE = re.compile(
    r"(status|state|origin|scope|marker|placeholder|unknown|pending|n_?a$|applicab)",
    re.IGNORECASE,
)


def _counter_to_dict(counter: Counter[str], keys: Iterable[str] = ()) -> dict[str, int]:
    out = {key: int(counter.get(key, 0)) for key in keys}
    out.update({key: int(value) for key, value in counter.items() if key not in out})
    return out


def mark_distribution(counts: Mapping[str, int], marker) -> dict[str, int]:
    """以 ``marker(value)`` 對聚合列計數，保留所有五個 L2 值域。"""
    out: Counter[str] = Counter()
    for value, count in counts.items():
        out[marker(value)] += int(count)
    return _counter_to_dict(out, MARKS)


def entity_categories(
    rows: Iterable[tuple[str | None, int]],
    core_lookup: Mapping[str, str],
    ext_lookup: Mapping[str, str],
) -> dict[str, int]:
    out: Counter[str] = Counter()
    for raw_type, count in rows:
        category = classify_entity_type_value(raw_type, core_lookup, ext_lookup)
        out[category] += int(count)
    return _counter_to_dict(out, ("empty", "concept_only", "standard", "standard_with_concept", "outside_raw"))


def entity_scheme_marks(
    rows: Iterable[tuple[str | None, int]],
    core_lookup: Mapping[str, str],
    ext_lookup: Mapping[str, str],
) -> dict[str, dict[str, int]]:
    rows = list(rows)
    out: dict[str, dict[str, int]] = {}
    for scheme in SCHEMES:
        counts: Counter[str] = Counter()
        for raw_type, count in rows:
            counts[mark_entity_type(raw_type, core_lookup, ext_lookup, scheme)] += int(count)
        out[scheme] = _counter_to_dict(counts, MARKS)
    return out


def relation_scheme_marks(rows: Iterable[tuple[str | None, int]]) -> dict[str, dict[str, int]]:
    """關係標示不受 concept_scheme 影響，但仍以三個 scheme 並列輸出。"""
    counts: Counter[str | None] = Counter()
    for rel_type, count in rows:
        counts[rel_type] += int(count)
    base = Counter()
    for rel_type, count in counts.items():
        base[mark_relation_type(rel_type)] += count
    base_dict = _counter_to_dict(base, MARKS)
    return {scheme: dict(base_dict) for scheme in SCHEMES}


def article_marks(citations_by_doc: Mapping[str, list[object]]) -> dict[str, int]:
    return mark_citations_by_document(citations_by_doc)


def empty_field_marks(rows: Iterable[tuple[bool, bool, bool, int]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for empty_subject, empty_object, empty_verb, count in rows:
        # 這裡把聚合的空白旗標轉回 L2 函式的明確輸入；沒有以真值判斷
        # None／空字串，Cypher 已先用 trim(coalesce(...)) 產生布林值。
        subject = "" if empty_subject else "主詞"
        obj = "" if empty_object else "受詞"
        verb = "" if empty_verb else "動詞"
        counts[mark_fact_fields(subject, obj, verb)] += int(count)
    return _counter_to_dict(counts, MARKS)


def normalized_phase0_marks(raw: Mapping[str, Any]) -> dict[str, dict[str, dict[str, int]]]:
    """把 Phase 0 的欄位名轉成 L2 值域，供逐項比較。"""
    def complete(values: Mapping[str, int]) -> dict[str, int]:
        return {mark: int(values.get(mark, 0)) for mark in MARKS}

    entity = {
        "strict": complete(raw["entity_type_marks"]["strict"]),
        "A": complete(raw["entity_type_marks"]["scheme_A_concept_as_unknown"]),
        "B": complete(raw["entity_type_marks"]["scheme_B_concept_as_real"]),
    }
    relation_strict = complete({
        "不適用": raw["rel_type_marks"]["strict"]["不適用"],
        RESOLVED: raw["rel_type_marks"]["strict"][RESOLVED],
        INDETERMINATE: raw["rel_type_marks"]["strict"]["無法由現有資料判定（RELATED_TO 來源不明）"],
    })
    relation = {scheme: dict(relation_strict) for scheme in SCHEMES}
    article = {
        "strict": complete({
            RESOLVED: raw["article_scope"]["known"],
            "不適用": raw["article_scope"]["not_applicable"],
            "未知": raw["article_scope"]["unknown"],
        })
    }
    article["A"] = dict(article["strict"])
    article["B"] = dict(article["strict"])
    empty = {
        "strict": complete({
            RESOLVED: raw["fact_empties"]["categories"]["complete"],
            "未知": raw["fact_empties"]["categories"]["unknown_determinate"],
            "尚未處理": raw["fact_empties"]["categories"]["pending_needs_human_or_llm"],
        })
    }
    empty["A"] = dict(empty["strict"])
    empty["B"] = dict(empty["strict"])
    return {"entity": entity, "relation": relation, "article": article, "empty": empty}


def compare_value(path: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "path": path,
        "expected_phase0": expected,
        "actual_l3": actual,
        "status": "一致" if expected == actual else "不一致",
    }


def build_comparison(raw: Mapping[str, Any], derived: Mapping[str, Any]) -> list[dict[str, Any]]:
    expected = normalized_phase0_marks(raw)
    comparisons: list[dict[str, Any]] = []
    comparisons.append(compare_value("entity_type_categories", raw["entity_type_categories"], derived["entity_type_categories"]))
    for scheme in SCHEMES:
        comparisons.append(compare_value(
            f"entity_type_marks.{scheme}", expected["entity"][scheme], derived["marks"]["entity"][scheme]
        ))
        comparisons.append(compare_value(
            f"relation_type_marks.{scheme}", expected["relation"][scheme], derived["marks"]["relation"][scheme]
        ))
        comparisons.append(compare_value(
            f"source_article_no_marks.{scheme}", expected["article"][scheme], derived["marks"]["article"][scheme]
        ))
        comparisons.append(compare_value(
            f"empty_field_marks.{scheme}", expected["empty"][scheme], derived["marks"]["empty"][scheme]
        ))
    comparisons.append(compare_value("fact_empties.combos", raw["fact_empties"]["combos"], derived["fact_empty_combos"]))
    comparisons.append(compare_value("before_totals", raw["before"], derived["before"]))
    comparisons.append(compare_value("after_totals", raw["after"], derived["after"]))
    return comparisons


def coverage_row(population: int, storage_marked: int, derived_not_indeterminate: int) -> dict[str, Any]:
    return {
        "population": population,
        "storage_explicit_marked": storage_marked,
        "storage_explicit_share": storage_marked / population if population else None,
        "derived_non_indeterminate": derived_not_indeterminate,
        "derived_non_indeterminate_share": derived_not_indeterminate / population if population else None,
        "note": "乙為查詢時派生函式的輸出，不代表已寫入儲存層。",
    }


def _marker_candidates(node_rows: Iterable[dict[str, Any]], edge_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for row in list(node_rows) + list(edge_rows):
        if _MARKER_KEY_RE.search(str(row.get("key", ""))):
            candidates.append(row)
    return candidates


def collect(
    driver: Any,
    kg_id: str,
    core_types: set[str],
    ext_json: Path,
    phase0_raw: Mapping[str, Any],
) -> dict[str, Any]:
    runner = ReadOnlyRunner(driver)
    before = totals(runner, kg_id, "before")
    if before != EXPECTED_TOTALS:
        raise SystemExit(f"資料量與預期不符，停止：{before}")

    core_lookup = {normalize_type_key(k): k for k in core_types}
    ext_payload = json.loads(ext_json.read_text(encoding="utf-8"))
    ext_lookup = {normalize_type_key(t["label"]): t["id"] for t in ext_payload.get("types", [])}

    node_keys = runner.run(
        "L3 儲存層節點屬性鍵",
        "MATCH (n {kg_id: $k}) UNWIND keys(n) AS key RETURN labels(n)[0] AS owner, key, count(*) AS n ORDER BY owner, n DESC",
        k=kg_id,
    )
    edge_keys = runner.run(
        "L3 儲存層關係屬性鍵",
        "MATCH ()-[r {kg_id: $k}]->() UNWIND keys(r) AS key RETURN type(r) AS owner, key, count(*) AS n ORDER BY owner, n DESC",
        k=kg_id,
    )
    marker_candidates = _marker_candidates(node_keys, edge_keys)
    storage_marked = 0 if not marker_candidates else None

    entity_rows = runner.run(
        "L3 Entity type 分布",
        "MATCH (e:Entity {kg_id: $k}) RETURN e.type AS t, count(*) AS n",
        k=kg_id,
    )
    entity_pairs = [(row["t"], row["n"]) for row in entity_rows]
    rel_rows = runner.run(
        "L3 Fact rel_type 分布",
        "MATCH (f:Fact {kg_id: $k}) RETURN f.rel_type AS t, count(*) AS n",
        k=kg_id,
    )
    rel_pairs = [(row["t"], row["n"]) for row in rel_rows]
    citation_rows = runner.run(
        "L3 事實邊 citations_json",
        "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.citations_json IS NOT NULL RETURN r.citations_json AS c",
        k=kg_id,
    )
    citations_by_doc: dict[str, list[object]] = {}
    for row in citation_rows:
        for citation in parse_citations(row.get("c")):
            document = str(citation.get("source_doc_id") or "None")
            citations_by_doc.setdefault(document, []).append(citation.get("article_no"))
    empty_rows = runner.run(
        "L3 Fact 空欄位組合",
        "MATCH (f:Fact {kg_id: $k}) RETURN trim(coalesce(f.subject, '')) = '' AS es, trim(coalesce(f.object, '')) = '' AS eo, trim(coalesce(f.verb, '')) = '' AS ev, count(*) AS n",
        k=kg_id,
    )
    empty_pairs = [(row["es"], row["eo"], row["ev"], row["n"]) for row in empty_rows]

    categories = entity_categories(entity_pairs, core_lookup, ext_lookup)
    marks = {
        "entity": entity_scheme_marks(entity_pairs, core_lookup, ext_lookup),
        "relation": relation_scheme_marks(rel_pairs),
        "article": {scheme: article_marks(citations_by_doc) for scheme in SCHEMES},
        "empty": {scheme: empty_field_marks(empty_pairs) for scheme in SCHEMES},
    }
    empty_all = marks["empty"]["strict"]
    empty_incomplete_population = empty_all.get("未知", 0) + empty_all.get("尚未處理", 0)
    after = totals(runner, kg_id, "after")
    derived = {
        "before": before,
        "entity_type_categories": categories,
        "marks": marks,
        "fact_empty_combos": {
            f"subject={int(es)},object={int(eo)},verb={int(ev)}": int(n)
            for es, eo, ev, n in empty_pairs
        },
        "storage_marker_candidates": marker_candidates,
        "after": after,
    }
    derived["comparison"] = build_comparison(phase0_raw, derived)
    if any(row["status"] == "不一致" for row in derived["comparison"]):
        # 這是停止條件：不替規則調整數字。
        raise SystemExit("L3 與 Phase 0 基準線不一致，已停止；請查看前述比較資料。")

    derived["after"] = totals(runner, kg_id, "after")
    if derived["after"] != before:
        raise SystemExit(f"唯讀前後總數不一致，停止：{before} -> {derived['after']}")
    if marker_candidates:
        raise SystemExit(f"發現可能的儲存層標示鍵，需人工判讀後停止：{marker_candidates}")

    storage = {key: coverage_row(population, 0, 0) for key, population in (
        ("entity_type", before["entities"]),
        ("relation_type", before["facts"]),
        ("source_article_no", sum(len(values) for values in citations_by_doc.values())),
        ("empty_fields_among_facts_with_any_empty", empty_incomplete_population),
    )}
    for scheme in SCHEMES:
        for key, marks_for_object, population in (
            ("entity_type", marks["entity"][scheme], before["entities"]),
            ("relation_type", marks["relation"][scheme], before["facts"]),
            ("source_article_no", marks["article"][scheme], sum(len(values) for values in citations_by_doc.values())),
            ("empty_fields_among_facts_with_any_empty", marks["empty"][scheme], empty_incomplete_population),
        ):
            if key == "empty_fields_among_facts_with_any_empty":
                # Phase 0 的母體排除完整 Fact；L2 對完整 Fact 回傳 RESOLVED，
                # 因此覆蓋率在這裡只統計該母體中的 UNKNOWN／PENDING。
                non_indeterminate = sum(
                    count for mark, count in marks_for_object.items() if mark in {"未知", "尚未處理"}
                )
            else:
                non_indeterminate = sum(
                    count for mark, count in marks_for_object.items() if mark != INDETERMINATE
                )
            storage[f"{key}.{scheme}"] = coverage_row(population, 0, non_indeterminate)
    derived["coverage"] = storage
    derived["phase0_baseline_reference"] = phase0_raw["baseline"]
    derived["totals_identical"] = derived["before"] == derived["after"]
    derived["cypher_log"] = runner.log
    return derived


def read_env_value(env_file: Path, key: str) -> str | None:
    """讀取單一 .env 值，不修改 ``os.environ``，也不輸出值。"""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*)$", line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--phase0-raw", type=Path, default=PHASE0_RAW_DEFAULT)
    parser.add_argument("--ext-types", type=Path, default=EXT_TYPES_DEFAULT)
    parser.add_argument("--kg-id", default=KG_ID_DEFAULT)
    parser.add_argument("--uri", default=BOLT_URI_DEFAULT)
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args(argv)
    password = args.password or (read_env_value(args.env_file, "NEO4J_PASSWORD") if args.env_file else None)
    if not password:
        raise SystemExit("需要 --password 或 --env-file")
    phase0_raw = json.loads(args.phase0_raw.read_text(encoding="utf-8"))
    from core.constants import ENTITY_TYPES  # noqa: PLC0415
    from neo4j import GraphDatabase  # noqa: PLC0415

    driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
    try:
        result = collect(driver, args.kg_id, set(ENTITY_TYPES), args.ext_types, phase0_raw)
    finally:
        driver.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "totals_identical": result["totals_identical"],
        "before": result["before"],
        "after": result["after"],
        "comparison": result["comparison"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
