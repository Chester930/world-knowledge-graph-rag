"""報告212 L1：「概念」Entity 的固定種子唯讀抽樣與原句材料。

母體是 ``Entity.type`` 精確等於「概念」的 Entity。候選名稱先以 Unicode
字面排序，再由 ``random.Random(seed).sample(..., 50)`` 無放回抽樣；空名
實體不預先排除，若抽中會在報告中照實呈現。每個樣本取最多 12 條有引用的
事實邊引用，依文件／chunk／三元組／句起等欄位穩定排序後保留前 12 條。

Neo4j 查詢只重用報告195／207 的 ``ReadOnlyRunner`` 與
``assert_read_only``；原句定位重用報告200 的 chunk＋子字串方法。匯入時
不連線、不讀取環境變數、不改 ``os.environ``，也不呼叫 LLM／embedding。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.empty_object_annotation import locate_original_sentence  # noqa: E402
from scripts.analysis.semantic_layer_invariants import (  # noqa: E402
    BOLT_URI_DEFAULT,
    EXPECTED_TOTALS,
    KG_ID_DEFAULT,
    ReadOnlyRunner,
    assert_read_only,
    parse_citations,
    totals,
)

SAMPLE_SEED = 20261012
SAMPLE_SIZE = 50
FACTS_PER_ENTITY = 12
KG_RUNTIME_DEFAULT = Path("D:/Users/666/Desktop/kg-runtime")


def _as_int(value: Any) -> int:
    return int(value) if value is not None else -1


def stable_record_key(record: dict[str, Any]) -> str:
    fields = (
        record.get("document", ""),
        str(record.get("chunk", "")),
        record.get("subject", ""),
        record.get("rel_type", ""),
        record.get("verb", ""),
        record.get("object", ""),
        str(record.get("source_sentence_start", "")),
        str(record.get("source_sentence_end", "")),
    )
    return "|".join(fields)


def sample_entities(rows: Iterable[dict[str, Any]], *, seed: int = SAMPLE_SEED, size: int = SAMPLE_SIZE) -> list[dict[str, Any]]:
    candidates = sorted(rows, key=lambda row: (str(row.get("name", "")), str(row.get("type", ""))))
    if len(candidates) < size:
        raise ValueError(f"母體只有 {len(candidates)}，少於要求的 {size} 筆")
    chosen = random.Random(seed).sample(candidates, size)
    chosen.sort(key=lambda row: (str(row.get("name", "")), str(row.get("type", ""))))
    return [{**row, "sample_key": f"{row.get('name', '')}|{row.get('type', '')}"} for row in chosen]


def _doc_name_by_id(kg_runtime: Path, kg_id: str) -> dict[str, str]:
    # DOCUMENT_ID_NAMESPACE 只在實際執行路徑匯入，避免匯入腳本帶入 core。
    from core.constants import DOCUMENT_ID_NAMESPACE

    root = kg_runtime / kg_id
    return {str(uuid.uuid5(DOCUMENT_ID_NAMESPACE, path.name)): path.name for path in root.iterdir() if path.is_dir()}


def _citation_records(edge_rows: Iterable[dict[str, Any]], doc_by_id: dict[str, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in edge_rows:
        for citation in parse_citations(row.get("citations")):
            doc_id = citation.get("source_doc_id")
            record = {
                "source_doc_id": doc_id,
                "document": doc_by_id.get(str(doc_id), str(doc_id or "")),
                "chunk": _as_int(citation.get("source_svo_chunk_index")),
                "chunk_file": citation.get("source_svo_chunk_file") or "",
                "source_sentence_start": citation.get("source_sentence_start"),
                "source_sentence_end": citation.get("source_sentence_end"),
                "subject": row.get("subject") or "",
                "rel_type": row.get("rel_type") or "",
                "verb": citation.get("verb") or "",
                "object": row.get("object") or "",
                "confidence": citation.get("confidence"),
                "article_no": citation.get("article_no"),
            }
            record["sample_key"] = stable_record_key(record)
            records.append(record)
    return records


def _sort_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda row: (
            row.get("document", ""),
            _as_int(row.get("chunk")),
            row.get("subject", ""),
            row.get("rel_type", ""),
            row.get("verb", ""),
            row.get("object", ""),
            _as_int(row.get("source_sentence_start")),
            _as_int(row.get("source_sentence_end")),
            row.get("sample_key", ""),
        ),
    )


def facts_for_entities(
    selected_names: set[str],
    edge_rows: Iterable[dict[str, Any]],
    doc_by_id: dict[str, str],
    *,
    limit: int | None = FACTS_PER_ENTITY,
) -> dict[str, list[dict[str, Any]]]:
    all_records = _citation_records(edge_rows, doc_by_id)
    by_entity: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in selected_names}
    for record in all_records:
        for name, role in ((record["subject"], "主詞"), (record["object"], "受詞")):
            if name in selected_names:
                key = record["sample_key"]
                by_entity[name].setdefault(key, {**record, "entity_role": role})
                if name == record["subject"] and name == record["object"]:
                    by_entity[name][key]["entity_role"] = "主詞／受詞"
    ordered = {name: _sort_records(values.values()) for name, values in by_entity.items()}
    return {name: records if limit is None else records[:limit] for name, records in ordered.items()}


def degrees_for_entities(selected_names: set[str], edge_rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    degrees = {name: 0 for name in selected_names}
    for row in edge_rows:
        subject = row.get("subject") or ""
        obj = row.get("object") or ""
        if subject in degrees:
            degrees[subject] += 1
        if obj in degrees:
            degrees[obj] += 1
    return degrees


def apply_draft_annotations(records: Iterable[dict[str, Any]], annotations: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for record in records:
        annotation = annotations.get(record["sample_key"], annotations.get(str(record["sample_number"]), {}))
        label = str(annotation.get("label", "U")).upper()
        if label not in {"P", "C", "U"}:
            raise ValueError(f"標註必須是 P/C/U：{record['sample_key']}")
        out.append({
            **record,
            "label": label,
            "suggested_schema_type": str(annotation.get("suggested_schema_type", "")),
            "question": bool(annotation.get("question", True if not annotation else False)),
            "reason": str(annotation.get("reason", "尚未完成草稿判讀；需人工確認。")),
        })
    return sorted(out, key=lambda row: (not row["question"], row["sample_number"]))


def locate_facts(records: Iterable[dict[str, Any]], kg_runtime: Path, kg_id: str) -> list[dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    out = []
    for record in records:
        cache_key = record["sample_key"]
        if cache_key not in cache:
            located = locate_original_sentence(record, kg_runtime, kg_id)
            if located.get("location_status") != "found":
                # 報告200 允許「找不到唯一原句」並列為疑問。若 chunk 只有
                # 一句，仍可逐字列出這個唯一 chunk 原句，但不宣稱它命中
                # 三元組錨點；多句無法唯一判斷時保留空字串並停止本次材料。
                doc_dir = kg_runtime / kg_id / record["document"]
                index_payload = json.loads((doc_dir / "svo_index.json").read_text(encoding="utf-8"))
                chunk = next(
                    (c for c in index_payload.get("chunks", []) if _as_int(c.get("index")) == _as_int(record.get("chunk"))),
                    None,
                )
                sentences = [str(s) for s in (chunk or {}).get("original_sentences", [])]
                original_path = doc_dir / "original.md"
                if len(sentences) == 1 and sentences[0] in original_path.read_text(encoding="utf-8"):
                    located = {
                        **located,
                        "chunk_sentence_index": 1,
                        "source_sentence": sentences[0],
                        "context_before": "",
                        "context_after": "",
                        "original_sentence_in_original_md": True,
                        "location_status": "chunk_only_no_anchor",
                    }
                else:
                    located = {
                        **located,
                        "chunk_sentence_index": None,
                        "source_sentence": "",
                        "chunk_sentence_candidates": sentences,
                        "context_before": "",
                        "context_after": "",
                        "original_sentence_in_original_md": False,
                        "location_status": "not_found",
                    }
            cache[cache_key] = located
        located = cache[cache_key]
        out.append({**record, **located})
    return out


def collect(
    driver: Any,
    kg_id: str,
    kg_runtime: Path,
    doc_by_id: dict[str, str],
    *,
    seed: int = SAMPLE_SEED,
    size: int = SAMPLE_SIZE,
) -> tuple[list[dict[str, Any]], int, dict[str, int], list[dict[str, Any]]]:
    runner = ReadOnlyRunner(driver)
    before = totals(runner, kg_id, "before")
    if before != EXPECTED_TOTALS:
        raise SystemExit(f"資料量與預期不符，停止：{before}")
    entity_rows = runner.run(
        "L1 Entity.type 精確等於概念母體",
        "MATCH (e:Entity {kg_id: $k}) WHERE e.type = '概念' RETURN e.name AS name, e.type AS type",
        k=kg_id,
    )
    selected = sample_entities(entity_rows, seed=seed, size=size)
    selected_names = {row["name"] for row in selected}
    edge_rows = runner.run(
        "L1 抽樣實體的事實邊與引用",
        "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k}) WHERE r.citations_json IS NOT NULL AND (s.name IN $names OR o.name IN $names) RETURN s.name AS subject, o.name AS object, type(r) AS rel_type, r.citations_json AS citations",
        k=kg_id,
        names=sorted(selected_names),
    )
    degrees = degrees_for_entities(selected_names, edge_rows)
    facts = facts_for_entities(selected_names, edge_rows, doc_by_id, limit=None)
    material: list[dict[str, Any]] = []
    for number, entity in enumerate(selected, start=1):
        name = entity["name"]
        material.append({
            **entity,
            "sample_number": number,
            "degree": degrees.get(name, 0),
            "fact_count_included": len(facts.get(name, [])),
            "facts": facts.get(name, []),
        })
    flat_facts = [fact for entity in material for fact in entity["facts"]]
    located = locate_facts(flat_facts, kg_runtime, kg_id)
    by_key = {fact["sample_key"]: fact for fact in located}
    for entity in material:
        candidates = [by_key[fact["sample_key"]] for fact in entity["facts"]]
        locatable = [fact for fact in candidates if fact.get("location_status") in {"found", "chunk_only_no_anchor"}]
        unlocatable = [fact for fact in candidates if fact.get("location_status") == "not_found"]
        entity["unlocatable_candidate_count"] = len(unlocatable)
        entity["facts"] = (locatable[:FACTS_PER_ENTITY] + unlocatable[: max(0, FACTS_PER_ENTITY - len(locatable))])
        entity["fact_count_included"] = len(entity["facts"])
    after = totals(runner, kg_id, "after")
    if after != before:
        raise SystemExit(f"唯讀前後總數不一致，停止：{before} -> {after}")
    return material, len(entity_rows), after, runner.log


def _md_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def write_outputs(
    records: list[dict[str, Any]],
    *,
    csv_path: Path,
    review_path: Path,
    raw_path: Path,
    annotations_path: Path,
    seed: int,
    population: int,
    before: dict[str, int],
    after: dict[str, int],
    cypher_log: list[dict[str, Any]],
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "編號", "名稱", "type", "度數", "納入事實數", "草稿標註", "標註狀態", "建議schema.org型別", "疑問", "理由",
        "事實JSON", "sample_key",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "編號": record["sample_number"],
                "名稱": record["name"],
                "type": record["type"],
                "度數": record["degree"],
                "納入事實數": record["fact_count_included"],
                "草稿標註": record["label"],
                "標註狀態": "草稿，未經使用者確認",
                "建議schema.org型別": record["suggested_schema_type"],
                "疑問": "是" if record["question"] else "否",
                "理由": record["reason"],
                "事實JSON": json.dumps(record["facts"], ensure_ascii=False, separators=(",", ":")),
                "sample_key": record["sample_key"],
            })
    lines = [
        "# L1「概念」實體抽樣審閱檔（草稿）",
        "",
        "> 以下標註、理由與疑問旗標全部是執行者草稿，**未經使用者確認，不是最終結論**。使用者只需回覆「第 N 筆改成 P／C／U」。",
        f"> 母體：Entity.type 精確等於「概念」共 {population:,} 個；固定種子 `{seed}`；抽法：候選以名稱／type 字面排序後，`random.Random({seed}).sample(..., 50)` 無放回抽樣，再按名稱／type 排序編號。",
        "> 每筆最多列 12 條有引用事實邊的引用；度數定義為事實邊入＋出，自環計 2；資料不足 12 條時照實列出。原句以報告200的方法由 chunk＋subject／verb 子字串比對，並確認逐字出現在 original.md；source_sentence_start/end 是 chunk 內相對範圍。",
        "> 草稿標準：P＝名稱有更合適的 schema.org 標準型別（附建議型別）；C＝目前證據顯示是制度、規定、狀態、數量、行為等抽象概念，沒有明顯更合適型別；U＝現有名稱與最多 12 條上下文不足以判斷。疑問旗標只表示執行者認為需要使用者看，疑問筆置前。",
        "",
        "| 編號 | 疑問 | 名稱 | 度數 | 草稿標註 | 建議 schema.org 型別 | 理由（草稿，未經使用者確認） |",
        "| ---: | :---: | --- | ---: | :---: | --- | --- |",
    ]
    for record in records:
        lines.append("| " + " | ".join((
            str(record["sample_number"]),
            "**是**" if record["question"] else "否",
            _md_cell(record["name"]),
            str(record["degree"]),
            record["label"],
            _md_cell(record["suggested_schema_type"]),
            _md_cell(record["reason"]),
        )) + " |")
        lines.append("")
        lines.append(f"**第 {record['sample_number']} 筆的事實（最多 12 條；草稿，未經使用者確認）**")
        lines.append("")
        lines.append("| 事實序號 | 角色 | 主詞 | rel_type | verb | 受詞 | 文件／chunk | 來源原句（被抽取句） | chunk 內範圍 |")
        lines.append("| ---: | :---: | --- | --- | --- | --- | --- | --- | --- |")
        for fact_number, fact in enumerate(record["facts"], start=1):
            if fact.get("location_status") == "not_found":
                sentence = "【找不到唯一原句；疑問；chunk 內逐字候選見下方】"
            else:
                sentence_status = "；未命中三元組錨點，疑問" if fact.get("location_status") == "chunk_only_no_anchor" else "；命中 subject／verb 子字串"
                sentence = f"【chunk 第 {fact['chunk_sentence_index']} 句{sentence_status}】{fact['source_sentence']}"
            lines.append("| " + " | ".join((
                str(fact_number), _md_cell(fact.get("entity_role", "")), _md_cell(fact.get("subject", "")),
                _md_cell(fact.get("rel_type", "")), _md_cell(fact.get("verb", "")), _md_cell(fact.get("object", "")),
                _md_cell(f"{fact.get('document', '')}／c{fact.get('chunk', '')}"), _md_cell(sentence),
                _md_cell(f"{fact.get('source_sentence_start', '')}–{fact.get('source_sentence_end', '')}"),
            )) + " |")
            if fact.get("location_status") == "not_found":
                candidates = fact.get("chunk_sentence_candidates", [])
                lines.append("|  |  |  |  |  |  |  | **chunk 內逐字候選（未能唯一對應）** | " + _md_cell("／".join(candidates)) + " |")
        lines.append("")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    raw_path.write_text(json.dumps({
        "seed": seed,
        "sample_size": len(records),
        "population_size": population,
        "facts_per_entity_limit": FACTS_PER_ENTITY,
        "sampling_method": "sort(name,type); random.Random(seed).sample(pool, 50); sort(name,type) for review numbering",
        "annotation_status": "草稿，未經使用者確認",
        "before": before,
        "after": after,
        "totals_identical": before == after,
        "records": records,
        "cypher_log": cypher_log,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    annotations_path.write_text(json.dumps({
        record["sample_key"]: {
            "label": record["label"],
            "annotation_status": "草稿，未經使用者確認",
            "suggested_schema_type": record["suggested_schema_type"],
            "question": record["question"],
            "reason": record["reason"],
        }
        for record in records
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_env_value(env_file: Path, key: str) -> str | None:
    """讀取單一 .env 值，不修改 ``os.environ``，也不輸出值。"""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*)$", line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def _load_annotations(path: Path | None) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--annotations", type=Path, default=None)
    parser.add_argument("--kg-id", default=KG_ID_DEFAULT)
    parser.add_argument("--kg-runtime", type=Path, default=KG_RUNTIME_DEFAULT)
    parser.add_argument("--uri", default=BOLT_URI_DEFAULT)
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=SAMPLE_SEED)
    args = parser.parse_args(argv)
    password = args.password or (read_env_value(args.env_file, "NEO4J_PASSWORD") if args.env_file else None)
    if not password:
        raise SystemExit("需要 --password 或 --env-file")
    doc_by_id = _doc_name_by_id(args.kg_runtime, args.kg_id)
    from neo4j import GraphDatabase  # noqa: PLC0415

    driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
    try:
        material, population, after, cypher_log = collect(
            driver, args.kg_id, args.kg_runtime, doc_by_id, seed=args.seed, size=SAMPLE_SIZE
        )
    finally:
        driver.close()
    annotations = _load_annotations(args.annotations)
    annotated = apply_draft_annotations(material, annotations)
    before = EXPECTED_TOTALS
    write_outputs(
        annotated,
        csv_path=args.csv,
        review_path=args.review,
        raw_path=args.raw,
        annotations_path=args.csv.with_name("214_L1概念實體抽樣草稿標註.json"),
        seed=args.seed,
        population=population,
        before=before,
        after=after,
        cypher_log=cypher_log,
    )
    print(json.dumps({
        "population": population,
        "sample": len(annotated),
        "seed": args.seed,
        "facts": sum(len(record["facts"]) for record in annotated),
        "question_flags": sum(1 for record in annotated if record["question"]),
        "before": before,
        "after": after,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
