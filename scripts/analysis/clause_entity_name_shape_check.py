"""報告225 Q3：用 `services.semantic_marks.mark_entity_name_shape()` 對已保存資料重算，與報告223 逐項對照。

**離線，不連 Neo4j／Ollama**。輸入皆為 repo 內已保存檔：
- `data/analysis/clause_entity_quantify_20261001.json`：報告223 O1 的彙總數字（對照基準）；
- `data/analysis/clause_entity_names_ge12_20261001.json`：長度 ≥12 字的 Entity 名稱與型別（O1 唯讀查詢結果的子集）；
- `data/analysis/clause_entity_sampling_material_20261001.json`：O2 的 50 筆樣本。

**限制（如實）**：名單只含 ≥12 字者，故可重算 ≥12 與 ≥20 兩檔；**≥8 檔與全圖 12,296 的分母無法由名單重算**
（8–11 字的名稱未保存），該兩項只能以 O1 JSON 內的數字自洽檢查，不列為「一致」。任何一項不一致即結束碼 1，
**不調整規則湊數字**。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services import semantic_marks as sm  # noqa: E402

DATA = _REPO / "data" / "analysis"
QUANT = DATA / "clause_entity_quantify_20261001.json"
NAMES = DATA / "clause_entity_names_ge12_20261001.json"
SAMPLE = DATA / "clause_entity_sampling_material_20261001.json"
CONCEPT = sm.CONCEPT_PLACEHOLDER


def recompute(entities: list[dict], threshold: int) -> dict[str, Any]:
    """以 Q1 函式對名單重算某門檻的分布（只含名單內 ≥threshold 者）。"""
    shapes: Counter = Counter()
    feats: Counter = Counter()
    concept = non_concept = 0
    for e in entities:
        shape = sm.mark_entity_name_shape(e["name"], threshold)
        shapes[shape] += 1
        if sm.is_suspected_clause_shape(shape):
            if e["type"] == CONCEPT:
                concept += 1
            else:
                non_concept += 1
            for label, hit in sm.name_shape_features(e["name"]).items():
                feats[label] += hit
    suspected = shapes[sm.NAME_SHAPE_CLAUSE_STRONG] + shapes[sm.NAME_SHAPE_CLAUSE_LENGTH_ONLY]
    return {"suspected": suspected, "strong": shapes[sm.NAME_SHAPE_CLAUSE_STRONG],
            "length_only": shapes[sm.NAME_SHAPE_CLAUSE_LENGTH_ONLY], "concept": concept,
            "non_concept": non_concept, "features": dict(feats)}


def _row(item: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {"item": item, "report223": expected, "recomputed": actual, "status": "一致" if expected == actual else "不一致"}


def compare(quant: dict, entities: list[dict], sample_records: list[dict]) -> list[dict]:
    rows: list[dict] = []
    by_th = quant["summary"]["by_threshold"]
    for th in (12, 20):
        r = recompute([e for e in entities if len(e["name"]) >= th], th)
        exp = by_th[str(th)]
        rows += [
            _row(f"≥{th} 字數量", exp["count"], r["suspected"]),
            _row(f"≥{th} 字 強候選（長度＋特徵）", exp["strong_candidates"], r["strong"]),
            _row(f"≥{th} 字 僅長度（＝數量−強候選）", exp["count"] - exp["strong_candidates"], r["length_only"]),
            _row(f"≥{th} 字 概念型別", exp["concept"], r["concept"]),
            _row(f"≥{th} 字 非概念型別", exp["non_concept"], r["non_concept"]),
            _row(f"≥{th} 字 特徵命中", exp["features"], r["features"]),
        ]
    # 報告223 彙總的強候選群組（主門檻 12）
    g = quant["groups"]["strong(len>=12+特徵)"]["count"]
    rows.append(_row("強候選群組實體數", g, recompute(entities, 12)["strong"]))
    # O2 的 50 筆：全部長度 ≥12，故每筆都應是「疑似子句」；length 欄位與名稱長度一致
    shapes = [sm.mark_entity_name_shape(r["name"]) for r in sample_records]
    rows.append(_row("O2 樣本數", 50, len(sample_records)))
    rows.append(_row("O2 樣本皆為疑似子句（長度≥12）", len(sample_records), sum(sm.is_suspected_clause_shape(s) for s in shapes)))
    rows.append(_row("O2 樣本 length 欄位與名稱長度一致", True, all(r["length"] == len(r["name"]) for r in sample_records)))
    return rows


def sample_shape_counts(sample_records: list[dict]) -> dict[str, int]:
    return dict(Counter(sm.mark_entity_name_shape(r["name"]) for r in sample_records))


def main() -> int:
    quant = json.loads(QUANT.read_text(encoding="utf-8"))
    entities = json.loads(NAMES.read_text(encoding="utf-8"))["entities"]
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))["records"]
    rows = compare(quant, entities, sample)
    bad = [r for r in rows if r["status"] != "一致"]
    out = {"rows": rows, "all_consistent": not bad, "o2_sample_shape_counts": sample_shape_counts(sample),
           "not_checkable": ["≥8 字檔（8–11 字名稱未保存）", "全圖 12,296 分母與全圖型別／度數分布"]}
    (DATA / "clause_entity_name_shape_check_20261001.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(r["status"], r["item"], r["report223"], r["recomputed"])
    print("全部一致" if not bad else f"不一致 {len(bad)} 項")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
