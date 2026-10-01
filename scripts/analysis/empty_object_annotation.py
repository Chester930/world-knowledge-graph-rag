"""K3 空受詞擴大標註材料的唯讀抽樣與原句定位工具。

本模組只讀 Neo4j 與 ``kg-runtime`` 的索引／原文檔案，不寫入圖譜，也不呼叫
LLM 或 embedding。Neo4j 查詢重用
``scripts.analysis.semantic_layer_invariants`` 的 ``ReadOnlyRunner`` 與
``assert_read_only``，session 仍由 runner 以 ``default_access_mode=READ`` 建立。

抽樣母體是「以空名 Entity 為受詞的事實邊之全部 citations_json 引用」；抽樣前
排除報告200 的既有 30 筆所在的文件＋chunk（比逐筆鍵更保守，保證不重疊），再
依報告200 的排序方式排序，以固定種子 ``20261001`` 抽 70 筆。原句定位沿用
報告200：用 chunk index 載入 ``original_sentences``，以 subject／verb 子字串
比對；``source_sentence_start/end`` 僅記錄 chunk 內相對範圍。

草稿標註由 ``--annotations`` 指定的 JSON 提供，格式為
``{sample_key: {"label": "a|b|c", "question": true|false, "reason": "..."}}``。
缺少的項目會保留為 ``c``／疑問，避免把未判讀資料誤寫成定論；輸出的所有
``label`` 都在檔案標題與欄位中標為「草稿、未經使用者確認」。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
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
    parse_citations,
    totals,
)

SAMPLE_SEED = 20261001
SAMPLE_SIZE = 70
KG_RUNTIME_DEFAULT = Path("D:/Users/666/Desktop/kg-runtime")
EXISTING_SAMPLE_SIZE = 30

# 報告200 §3 的既有 30 筆所在文件＋chunk。排除整個 chunk 是保守做法：即使
# 同一 chunk 還有其他引用，也不會把既有樣本誤抽進來。
EXISTING_30_CHUNKS: frozenset[tuple[str, int]] = frozenset({
    ("N0060014_營造安全衛生設施標準", 115),
    ("N0060027_職業安全衛生管理辦法", 17),
    ("N0060009_職業安全衛生設施規則", 260),
    ("N0060014_營造安全衛生設施標準", 9),
    ("N0020001_工會法", 33),
    ("N0080014_技術士技能檢定作業及試場規則", 59),
    ("N0090001_就業服務法", 55),
    ("N0060014_營造安全衛生設施標準", 138),
    ("N0060009_職業安全衛生設施規則", 172),
    ("N0060009_職業安全衛生設施規則", 83),
    ("N0090064_外國技術人力工作資格及許可管理辦法", 32),
    ("N0060014_營造安全衛生設施標準", 104),
    ("N0090025_就業促進津貼實施辦法", 24),
    ("N0060015_特定化學物質危害預防標準", 44),
    ("N0020007_勞資爭議處理法", 37),
    ("N0090002_私立就業服務機構許可及管理辦法", 12),
    ("N0090064_外國技術人力工作資格及許可管理辦法", 34),
    ("N0060027_職業安全衛生管理辦法", 18),
    ("N0080044_技能競賽實施及獎勵辦法", 15),
    ("N0090001_就業服務法", 40),
    ("N0060009_職業安全衛生設施規則", 38),
    ("N0080044_技能競賽實施及獎勵辦法", 30),
    ("N0050002_勞工保險條例施行細則", 98),
    ("N0090002_私立就業服務機構許可及管理辦法", 14),
    ("N0060014_營造安全衛生設施標準", 24),
    ("N0060015_特定化學物質危害預防標準", 47),
    ("N0060014_營造安全衛生設施標準", 37),
    ("N0060030_高壓氣體勞工安全規則", 195),
    ("N0060015_特定化學物質危害預防標準", 19),
    ("N0020006_團體協約法", 22),
})


def _as_int(value: Any) -> int:
    return int(value) if value is not None else -1


def record_key(record: dict[str, Any]) -> str:
    """回傳可放入 CSV／標註 JSON 的穩定鍵。"""
    fields = (
        record.get("document", ""),
        str(record.get("chunk", "")),
        record.get("subject", ""),
        record.get("rel_type", ""),
        record.get("verb", ""),
        str(record.get("source_sentence_start", "")),
        str(record.get("source_sentence_end", "")),
    )
    return "|".join(fields)


def citations_to_records(edge_rows: Iterable[dict[str, Any]], doc_by_id: dict[str, str]) -> list[dict[str, Any]]:
    """把事實邊列拆成「每個 citation 一筆」的 K3 母體記錄。"""
    records: list[dict[str, Any]] = []
    for row in edge_rows:
        for citation in parse_citations(row.get("citations")):
            doc_id = citation.get("source_doc_id")
            document = doc_by_id.get(str(doc_id), str(doc_id or ""))
            record = {
                "source_doc_id": doc_id,
                "document": document,
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
            record["sample_key"] = record_key(record)
            records.append(record)
    return records


def sorted_candidates(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """依報告200 的文件／chunk／三元組／句起排序。"""
    return sorted(
        records,
        key=lambda r: (
            r.get("document", ""),
            _as_int(r.get("chunk")),
            r.get("subject", ""),
            r.get("verb", ""),
            _as_int(r.get("source_sentence_start")),
            r.get("rel_type", ""),
            _as_int(r.get("source_sentence_end")),
            r.get("sample_key", ""),
        ),
    )


def sample_new_records(records: Iterable[dict[str, Any]], *, seed: int = SAMPLE_SEED, size: int = SAMPLE_SIZE) -> list[dict[str, Any]]:
    """排除既有 30 筆所在 chunk 後，以固定種子抽樣。"""
    pool = [r for r in sorted_candidates(records) if (r.get("document", ""), _as_int(r.get("chunk"))) not in EXISTING_30_CHUNKS]
    if len(pool) < size:
        raise ValueError(f"排除既有 30 筆後母體只有 {len(pool)} 筆，少於要求的 {size} 筆")
    selected = random.Random(seed).sample(pool, size)
    selected = sorted(selected, key=lambda r: r["sample_key"])
    return [{**record, "selection_index": i} for i, record in enumerate(selected, start=1)]


def _anchor_candidates(sentences: list[str], subject: str, verb: str) -> list[int]:
    """沿用報告200：先用 verb／subject 前六字作 chunk 內子字串比對。"""
    def compact(value: str) -> str:
        return re.sub(r"[\s，。；、：！？（）()「」『』【】\[\]…]", "", value)

    compact_sentences = [compact(sentence) for sentence in sentences]
    anchors = [compact(x[:6]) for x in (verb.strip(), subject.strip()) if x.strip()]
    anchors = list(dict.fromkeys(anchors))
    hits = [i for i, sentence in enumerate(compact_sentences) if any(a and a in sentence for a in anchors)]
    if hits:
        return hits
    # 少數 verb／subject 本身可能被切短，再以完整欄位作保守 fallback。
    full = [compact(x) for x in (verb.strip(), subject.strip()) if x]
    return [i for i, sentence in enumerate(compact_sentences) if any(x in sentence for x in full)]


def locate_original_sentence(record: dict[str, Any], kg_dir: Path, kg_id: str) -> dict[str, Any]:
    """以 chunk＋子字串找到原句，並確認原句逐字出現在 original.md。"""
    doc_dir = kg_dir / kg_id / record["document"]
    index_path = doc_dir / "svo_index.json"
    original_path = doc_dir / "original.md"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    chunk = next((c for c in payload.get("chunks", []) if _as_int(c.get("index")) == _as_int(record.get("chunk"))), None)
    if chunk is None:
        raise ValueError(f"找不到 chunk：{record['document']} c{record['chunk']}")
    sentences = [str(s) for s in chunk.get("original_sentences", [])]
    hits = _anchor_candidates(sentences, record.get("subject", ""), record.get("verb", ""))
    if not hits:
        return {
            **record,
            "chunk_source_sentence_start": chunk.get("source_sentence_start"),
            "chunk_source_sentence_end": chunk.get("source_sentence_end"),
            "chunk_sentence_index": None,
            "source_sentence": "",
            "context_before": "",
            "context_after": "",
            "original_sentence_in_original_md": False,
            "location_status": "not_found",
        }
    # 若同一 chunk 多句命中，優先同時含完整 verb／subject，再取較長 anchor 命中者。
    def score(i: int) -> tuple[int, int, int]:
        sentence = sentences[i]
        full_score = int(bool(record.get("verb") and record["verb"].strip() in sentence)) + int(bool(record.get("subject") and record["subject"].strip() in sentence))
        anchor_score = sum(1 for a in (record.get("verb", "")[:6], record.get("subject", "")[:6]) if a and a in sentence)
        return (full_score, anchor_score, -i)

    chosen = max(hits, key=score)
    sentence = sentences[chosen]
    original_text = original_path.read_text(encoding="utf-8")
    in_original = sentence in original_text
    return {
        **record,
        "chunk_source_sentence_start": chunk.get("source_sentence_start"),
        "chunk_source_sentence_end": chunk.get("source_sentence_end"),
        "chunk_sentence_index": chosen + 1,
        "source_sentence": sentence,
        "context_before": sentences[chosen - 1] if chosen > 0 else "",
        "context_after": sentences[chosen + 1] if chosen + 1 < len(sentences) else "",
        "original_sentence_in_original_md": in_original,
        "location_status": "found" if in_original else "not_in_original_md",
    }


def apply_annotations(records: Iterable[dict[str, Any]], annotations: dict[str, Any]) -> list[dict[str, Any]]:
    """套用草稿標註；未提供者保守標成 c／疑問。"""
    out: list[dict[str, Any]] = []
    for record in records:
        a = annotations.get(record["sample_key"], annotations.get(str(record.get("selection_index")), {}))
        label = str(a.get("label", "c")).lower()
        if label not in {"a", "b", "c"}:
            raise ValueError(f"標籤必須是 a/b/c：{record['sample_key']}")
        out.append({
            **record,
            "label": label,
            "question": bool(a.get("question", True if "label" not in a else False)),
            "reason": str(a.get("reason", "尚未完成草稿判讀；需人工確認。")),
        })
    return out


def order_for_review(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """疑問筆在前，其餘依穩定 sample_key 排序，最後才編使用者看到的編號。"""
    ordered = sorted(records, key=lambda r: (not r["question"], r["sample_key"]))
    return [{**r, "review_number": i} for i, r in enumerate(ordered, start=1)]


def _md_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def write_outputs(records: list[dict[str, Any]], *, csv_path: Path, review_path: Path, raw_path: Path, seed: int, excluded_count: int, population_count: int) -> None:
    questions = sum(1 for r in records if r["question"])
    if questions > len(records) / 2:
        raise ValueError(f"疑問旗標 {questions}/{len(records)} 超過一半，依報告207 §4 停止輸出")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "編號", "草稿標註", "疑問", "理由", "文件", "chunk", "source_doc_id", "rel_type", "verb", "object", "subject",
        "source_sentence_start", "source_sentence_end", "chunk_source_sentence_start", "chunk_source_sentence_end",
        "chunk_sentence_index", "原句", "前句", "後句", "chunk_file", "sample_key",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow({
                "編號": r["review_number"], "草稿標註": r["label"], "疑問": "是" if r["question"] else "否", "理由": r["reason"],
                "文件": r["document"], "chunk": r["chunk"], "source_doc_id": r["source_doc_id"], "rel_type": r["rel_type"],
                "verb": r["verb"], "object": r["object"], "subject": r["subject"], "source_sentence_start": r["source_sentence_start"],
                "source_sentence_end": r["source_sentence_end"], "chunk_source_sentence_start": r["chunk_source_sentence_start"],
                "chunk_source_sentence_end": r["chunk_source_sentence_end"], "chunk_sentence_index": r["chunk_sentence_index"],
                "原句": r["source_sentence"], "前句": r["context_before"], "後句": r["context_after"], "chunk_file": r["chunk_file"],
                "sample_key": r["sample_key"],
            })
    review_lines = [
        "# K3 空受詞擴大標註審閱檔（草稿）",
        "",
        "> 以下 70 筆是執行對話草稿，**所有標註與疑問旗標均未經使用者確認，不是最終結論**。",
        f"> 抽法：母體 {population_count} 筆；排除既有 30 筆所在的 {excluded_count} 個文件＋chunk；固定種子 `{seed}`；排序後抽 70 筆。疑問 {questions}/{len(records)}（{questions / len(records):.1%}）。",
        "> 標準沿用報告200 §3：`a`＝原句本來沒有受詞；`b`＝受詞被併進 verb；`c`＝無法判斷。使用者只需回覆「第 N 筆改成 X」。",
        "",
        "| 編號 | 疑問 | 草稿標註 | 文件／chunk | 三元組（主詞／rel_type／verb／受詞） | 來源原句（標明被抽取句） | 理由（草稿，未經使用者確認） |",
        "| ---: | :---: | :---: | --- | --- | --- | --- |",
    ]
    for r in records:
        q = "**是**" if r["question"] else "否"
        triple = "／".join((r["subject"], r["rel_type"], r["verb"], r["object"]))
        sentence = f"【chunk 第 {r['chunk_sentence_index']} 句】{r['source_sentence']}" if r["source_sentence"] else "【找不到唯一原句】"
        review_lines.append("| " + " | ".join((_md_cell(r["review_number"]), q, r["label"], _md_cell(f"{r['document']}／c{r['chunk']}"), _md_cell(triple), _md_cell(sentence), _md_cell(r["reason"]))) + " |")
    review_path.write_text("\n".join(review_lines) + "\n", encoding="utf-8")
    raw_path.write_text(json.dumps({
        "seed": seed, "sample_size": len(records), "population_size": population_count,
        "existing_sample_size": EXISTING_SAMPLE_SIZE, "excluded_chunk_count": excluded_count,
        "excluded_chunks": sorted([list(x) for x in EXISTING_30_CHUNKS]),
        "sampling_method": "sort(document, chunk, subject, verb, source_sentence_start, rel_type, source_sentence_end, sample_key); random.Random(seed).sample(pool, 70); exclude all records in existing-30 document+chunk pairs",
        "annotation_status": "草稿，未經使用者確認",
        "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def collect(driver: Any, kg_id: str, kg_runtime: Path, doc_by_id: dict[str, str], *, seed: int = SAMPLE_SEED, size: int = SAMPLE_SIZE) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    runner = ReadOnlyRunner(driver)
    before = totals(runner, kg_id, "before")
    if before != EXPECTED_TOTALS:
        raise SystemExit(f"資料量與預期不符，停止：{before}")
    rows = runner.run(
        "K3 空名 Entity 為受詞的全部引用",
        "MATCH (s:Entity {kg_id: $k})-[r]->(o:Entity {kg_id: $k, name: ''}) WHERE r.citations_json IS NOT NULL RETURN type(r) AS rel_type, s.name AS subject, o.name AS object, r.citations_json AS citations",
        k=kg_id,
    )
    all_records = citations_to_records(rows, doc_by_id)
    selected = sample_new_records(all_records, seed=seed, size=size)
    located = [locate_original_sentence(r, kg_runtime, kg_id) for r in selected]
    after = totals(runner, kg_id, "after")
    if after != before:
        raise SystemExit(f"唯讀前後總數不一致，停止：{before} -> {after}")
    return located, runner.log, len(all_records)


def _load_annotations(path: Path | None) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def read_env_value(env_file: Path, key: str) -> str | None:
    """讀取單一 .env 值，不修改 os.environ，也不輸出值。"""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*)$", line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--review", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--annotations", type=Path, default=None)
    ap.add_argument("--selected-out", type=Path, default=None, help="只輸出已抽樣／定位的原始候選 JSON，供草稿判讀")
    ap.add_argument("--inspect-only", action="store_true", help="只做唯讀抽樣與原句定位，不輸出審閱檔")
    ap.add_argument("--kg-id", default=KG_ID_DEFAULT)
    ap.add_argument("--kg-runtime", type=Path, default=KG_RUNTIME_DEFAULT)
    ap.add_argument("--uri", default=BOLT_URI_DEFAULT)
    ap.add_argument("--user", default="neo4j")
    ap.add_argument("--password", default=None)
    ap.add_argument("--env-file", type=Path, default=None, help="從該 .env 讀 NEO4J_PASSWORD，不修改環境變數")
    ap.add_argument("--seed", type=int, default=SAMPLE_SEED)
    args = ap.parse_args(argv)

    password = args.password or (read_env_value(args.env_file, "NEO4J_PASSWORD") if args.env_file else None)
    if not password:
        raise SystemExit("需要 --password 或 --env-file")

    from core.constants import DOCUMENT_ID_NAMESPACE  # noqa: PLC0415
    from neo4j import GraphDatabase  # noqa: PLC0415

    folders = [p for p in (args.kg_runtime / args.kg_id).iterdir() if p.is_dir()]
    doc_by_id = {str(__import__("uuid").uuid5(DOCUMENT_ID_NAMESPACE, p.name)): p.name for p in folders}
    driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
    try:
        selected, cypher_log, population = collect(driver, args.kg_id, args.kg_runtime, doc_by_id, seed=args.seed)
    finally:
        driver.close()
    if args.selected_out:
        args.selected_out.parent.mkdir(parents=True, exist_ok=True)
        args.selected_out.write_text(json.dumps({"seed": args.seed, "population": population, "records": selected}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.inspect_only:
        print(json.dumps({"population": population, "sample": len(selected), "seed": args.seed, "inspect_only": True}, ensure_ascii=False))
        return 0
    annotations = _load_annotations(args.annotations)
    records = order_for_review(apply_annotations(selected, annotations))
    write_outputs(records, csv_path=args.csv, review_path=args.review, raw_path=args.raw, seed=args.seed,
                  excluded_count=len(EXISTING_30_CHUNKS), population_count=population)
    print(json.dumps({
        "population": population, "sample": len(records), "seed": args.seed,
        "questions": sum(1 for r in records if r["question"]),
        "cypher": cypher_log,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
