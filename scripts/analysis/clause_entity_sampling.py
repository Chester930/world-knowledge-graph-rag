"""報告223 O2：長度 ≥12 字 Entity 的固定種子抽樣、原句材料與 S／L／U 草稿統計。

兩步驟（皆離線，**不連 DB**；DB 母體由 `clause_entity_quantify.py` 在唯讀 session 內另存）：
- `material`：讀母體 JSON（≥12 字 Entity＋其事實邊）→ `random.Random(seed).sample` 抽 50 → 取事實與來源原句
  （沿用報告200／214 的 chunk＋子字串取原句法，直接重用 `concept_entity_sampling` 的函式）。
- `render`：讀 material＋草稿標註 JSON → 審閱檔（疑問置前）＋CSV＋Wilson 統計。

草稿標註 S＝子句、L＝合法長名稱、U＝無法判斷；**一律標「未經使用者確認」**，不是最終結論。
匯入不連線、不改 `os.environ`、不呼叫 LLM／embedding。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis import concept_entity_sampling as ces  # noqa: E402
from scripts.analysis.empty_object_annotation_stats import wilson_interval  # noqa: E402
from scripts.analysis.semantic_layer_invariants import KG_ID_DEFAULT  # noqa: E402

SEED = 20261014
SIZE = 50
MIN_LEN = 12
LABELS = ("S", "L", "U")
STATUS = "草稿，未經使用者確認"


def population(entities: Iterable[dict], min_len: int = MIN_LEN) -> list[dict]:
    return [e for e in entities if len(e.get("name") or "") >= min_len]


def build_material(pool: dict, doc_by_id: dict[str, str], *, seed: int = SEED, size: int = SIZE) -> tuple[list[dict], int]:
    """純運算（不含原句定位）：抽樣＋度數＋文件數＋事實。回傳 (material, 母體大小)。"""
    pop = population(pool["entities"])
    selected = ces.sample_entities(pop, seed=seed, size=size)
    names = {r["name"] for r in selected}
    edges = pool["edges"]
    degrees = ces.degrees_for_entities(names, edges)
    docs: dict[str, set[str]] = {n: set() for n in names}
    for r in edges:
        for c in ces.parse_citations(r.get("citations")):
            d = c.get("source_doc_id")
            if d:
                for n in (r.get("subject"), r.get("object")):
                    if n in docs:
                        docs[n].add(str(d))
    facts = ces.facts_for_entities(names, edges, doc_by_id, limit=None)
    out = []
    for number, e in enumerate(selected, start=1):
        out.append({**e, "sample_number": number, "length": len(e["name"]), "degree": degrees.get(e["name"], 0),
                    "doc_count": len(docs[e["name"]]), "facts": facts.get(e["name"], [])})
    return out, len(pop)


def attach_sentences(material: list[dict], kg_runtime: Path, kg_id: str) -> list[dict]:
    """為每個樣本最多取 `FACTS_PER_ENTITY` 條事實並定位原句（優先可定位者，同 L1）。"""
    flat = [f for e in material for f in e["facts"]]
    located = ces.locate_facts(flat, kg_runtime, kg_id)
    by_key = {f["sample_key"]: f for f in located}
    for e in material:
        cands = [by_key[f["sample_key"]] for f in e["facts"]]
        ok = [f for f in cands if f.get("location_status") in {"found", "chunk_only_no_anchor"}]
        bad = [f for f in cands if f.get("location_status") == "not_found"]
        e["unlocatable_candidate_count"] = len(bad)
        e["facts"] = ok[: ces.FACTS_PER_ENTITY] + bad[: max(0, ces.FACTS_PER_ENTITY - len(ok))]
        e["fact_count_included"] = len(e["facts"])
    return material


def apply_annotations(material: list[dict], annotations: dict[str, Any]) -> list[dict]:
    """套用草稿標註（以 sample_key 或編號字串為鍵）。缺標註者為 U＋疑問。疑問置前。"""
    out = []
    for r in material:
        a = annotations.get(r["sample_key"], annotations.get(str(r["sample_number"]), {}))
        label = str(a.get("label", "U")).upper()
        if label not in LABELS:
            raise ValueError(f"標註必須是 S/L/U：{r['sample_key']}")
        out.append({**r, "label": label, "question": bool(a.get("question", not a)),
                    "reason": str(a.get("reason", "尚未完成草稿判讀；需人工確認。"))})
    return sorted(out, key=lambda r: (not r["question"], r["sample_number"]))


def summarize(records: list[dict]) -> dict[str, Any]:
    counts = Counter(r["label"] for r in records)
    n = len(records)
    labels = {}
    for lab in LABELS:
        lo, hi = wilson_interval(counts.get(lab, 0), n)
        labels[lab] = {"count": counts.get(lab, 0), "share": counts.get(lab, 0) / n if n else None,
                       "wilson_95": [lo, hi] if lo is not None else None}
    q = sum(1 for r in records if r["question"])
    qlo, qhi = wilson_interval(q, n)
    return {"status": STATUS, "total": n, "labels": labels,
            "question_flags": {"count": q, "share": q / n if n else None, "wilson_95": [qlo, qhi] if qlo is not None else None}}


def _md(v: Any) -> str:
    return str(v if v is not None else "").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def write_outputs(records: list[dict], *, csv_path: Path, review_path: Path, stats_path: Path, seed: int, pop_size: int) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["編號", "名稱", "type", "字數", "度數", "文件數", "納入事實數", "草稿標註", "標註狀態", "疑問", "理由", "事實JSON", "sample_key"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow({"編號": r["sample_number"], "名稱": r["name"], "type": r["type"], "字數": r["length"],
                        "度數": r["degree"], "文件數": r["doc_count"], "納入事實數": r["fact_count_included"],
                        "草稿標註": r["label"], "標註狀態": STATUS, "疑問": "是" if r["question"] else "否",
                        "理由": r["reason"], "事實JSON": json.dumps(r["facts"], ensure_ascii=False, separators=(",", ":")),
                        "sample_key": r["sample_key"]})
    lines = [
        "# O2 長名稱實體抽樣審閱檔（草稿）",
        "",
        "> 以下標註、理由與疑問旗標全部是執行者草稿，**未經使用者確認，不是最終結論**。使用者只需回覆「第 N 筆改成 S／L／U」。",
        f"> 母體：Entity 名稱長度 ≥{MIN_LEN} 字共 {pop_size:,} 個；固定種子 `{seed}`；抽法：候選以名稱／type 字面排序後 `random.Random({seed}).sample(..., {SIZE})` 無放回抽樣，再按名稱／type 排序編號。",
        "> 每筆最多列 12 條有引用事實邊的引用；度數＝事實邊入＋出（自環計 2）；文件數＝端點事實邊引用的不同文件數；原句以報告200的方法由 chunk＋子字串比對並確認逐字出現在 original.md（source_sentence_start/end 為 chunk 內相對範圍）。",
        "> 草稿標準：S＝名稱是一整句或半句條文，拆成「主體＋條件／行為」更合理；L＝合法長名稱（法規名稱、機構全名、專有名詞等，長是正常的）；U＝名稱與最多 12 條上下文不足以判斷。疑問筆置前。",
        "",
        "| 編號 | 疑問 | 名稱 | 字數 | 度數 | 文件數 | 草稿標註 | 理由（草稿，未經使用者確認） |",
        "| ---: | :---: | --- | ---: | ---: | ---: | :---: | --- |",
    ]
    for r in records:
        lines.append("| " + " | ".join((str(r["sample_number"]), "**是**" if r["question"] else "否", _md(r["name"]),
                                          str(r["length"]), str(r["degree"]), str(r["doc_count"]), r["label"], _md(r["reason"]))) + " |")
        lines += ["", f"**第 {r['sample_number']} 筆的事實（最多 12 條；草稿，未經使用者確認）**", "",
                  "| 事實序號 | 角色 | 主詞 | rel_type | verb | 受詞 | 文件／chunk | 來源原句（被抽取句） | chunk 內範圍 |",
                  "| ---: | :---: | --- | --- | --- | --- | --- | --- | --- |"]
        for i, f in enumerate(r["facts"], start=1):
            if f.get("location_status") == "not_found":
                sent = "【找不到唯一原句；疑問；chunk 內逐字候選見下方】"
            else:
                note = "；未命中三元組錨點，疑問" if f.get("location_status") == "chunk_only_no_anchor" else "；命中 subject／verb 子字串"
                sent = f"【chunk 第 {f['chunk_sentence_index']} 句{note}】{f['source_sentence']}"
            lines.append("| " + " | ".join((str(i), _md(f.get("entity_role", "")), _md(f.get("subject", "")), _md(f.get("rel_type", "")),
                                              _md(f.get("verb", "")), _md(f.get("object", "")),
                                              _md(f"{f.get('document', '')}／c{f.get('chunk', '')}"), _md(sent),
                                              _md(f"{f.get('source_sentence_start', '')}–{f.get('source_sentence_end', '')}"))) + " |")
            if f.get("location_status") == "not_found":
                lines.append("|  |  |  |  |  |  |  | **chunk 內逐字候選（未能唯一對應）** | " + _md("／".join(f.get("chunk_sentence_candidates", []))) + " |")
        lines.append("")
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stats_path.write_text(json.dumps({**summarize(records), "seed": seed, "population_size": pop_size},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("material")
    m.add_argument("--pool", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--kg-runtime", type=Path, default=ces.KG_RUNTIME_DEFAULT)
    m.add_argument("--kg-id", default=KG_ID_DEFAULT)
    m.add_argument("--seed", type=int, default=SEED)
    r = sub.add_parser("render")
    r.add_argument("--material", type=Path, required=True)
    r.add_argument("--annotations", type=Path, required=True)
    r.add_argument("--csv", type=Path, required=True)
    r.add_argument("--review", type=Path, required=True)
    r.add_argument("--stats", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "material":
        pool = json.loads(args.pool.read_text(encoding="utf-8"))
        doc_by_id = ces._doc_name_by_id(args.kg_runtime, args.kg_id)
        material, pop = build_material(pool, doc_by_id, seed=args.seed)
        material = attach_sentences(material, args.kg_runtime, args.kg_id)
        args.out.write_text(json.dumps({"seed": args.seed, "population_size": pop, "min_len": MIN_LEN,
                                        "annotation_status": STATUS, "records": material}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(json.dumps({"population": pop, "sample": len(material), "seed": args.seed,
                          "facts": sum(len(e["facts"]) for e in material)}, ensure_ascii=False))
        return 0
    data = json.loads(args.material.read_text(encoding="utf-8"))
    ann = json.loads(args.annotations.read_text(encoding="utf-8"))
    records = apply_annotations(data["records"], ann)
    write_outputs(records, csv_path=args.csv, review_path=args.review, stats_path=args.stats,
                  seed=data["seed"], pop_size=data["population_size"])
    print(json.dumps(summarize(records), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
