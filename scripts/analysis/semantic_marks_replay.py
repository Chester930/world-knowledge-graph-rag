"""報告217 M2：離線重放既有已保存的檢索 trace，統計「被檢索／進 prompt」事實的可派生標示分布。

純離線：只讀 `data/eval/**/records*.json`，不連 Neo4j／Ollama／LLM／embedding，不改任何 production 檔。
只描述分布，不宣稱品質改善。

**重放缺口（如實）**：已保存 trace 每筆只有 `kind／rank／text／score／source_doc_id／
source_svo_chunk_index／article_no／in_prompt`——沒有 subject／object／verb／rel_type／實體型別，
因此 `fields`／`relation_type`／實體型別三類標示**無法重放**（以 whitespace 切 `text` 推測空欄位不可靠：
主詞／受詞本身含空白，見報告217 §3）。可重放的只有 `article_no`（有／無）與 `in_prompt`。
`article_no` 無值時，文件層是否「適用條號」在 trace 內不可知，依 M1 語意標為「無法由現有資料判定」。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services import semantic_marks as sm  # noqa: E402

EVAL_DIR = ROOT / "data" / "eval"
OUT_JSON = ROOT / "data" / "analysis" / "semantic_marks_replay_20261001.json"


def iter_trace_entries(records: object) -> Iterator[tuple[str, dict]]:
    """從 records.json 取出 (question_id, trace entry)。trace 為 list（entries）或 dict（facts／triples）。"""
    if not isinstance(records, list):
        return
    for rec in records:
        if not isinstance(rec, dict):
            continue
        trace = ((rec.get("lineage") or {}).get("stage1_retrieval") or {}).get("retrieval_trace")
        if isinstance(trace, dict):
            entries = list(trace.get("facts") or []) + list(trace.get("triples") or [])
        elif isinstance(trace, list):
            entries = trace
        else:
            continue
        for e in entries:
            if isinstance(e, dict) and e.get("kind") in ("fact", "triple"):
                yield str(rec.get("question_id")), e


def article_mark(entry: dict) -> str:
    """與 M1 語意一致：有條號＝已解決；無條號且文件層資訊不可得＝無法由現有資料判定。"""
    return sm.RESOLVED if sm.has_article_no(entry.get("article_no")) else sm.INDETERMINATE


def summarize(entries: Iterable[tuple[str, dict]]) -> dict:
    """彙整一批 entries。`in_prompt` 為 None（未量測）者另計，不併入 True／False。"""
    out: dict = {"questions": set(), "by_kind": {}}
    for qid, e in entries:
        out["questions"].add(qid)
        kind = e["kind"]
        k = out["by_kind"].setdefault(
            kind,
            {"retrieved": 0, "in_prompt_true": 0, "in_prompt_false": 0, "in_prompt_unmeasured": 0,
             "article_retrieved": Counter(), "article_in_prompt": Counter()},
        )
        k["retrieved"] += 1
        ip = e.get("in_prompt")
        mark = article_mark(e)
        k["article_retrieved"][mark] += 1
        if ip is True:
            k["in_prompt_true"] += 1
            k["article_in_prompt"][mark] += 1
        elif ip is False:
            k["in_prompt_false"] += 1
        else:
            k["in_prompt_unmeasured"] += 1
    out["questions"] = len(out["questions"])
    for k in out["by_kind"].values():
        k["article_retrieved"] = dict(k["article_retrieved"])
        k["article_in_prompt"] = dict(k["article_in_prompt"])
    return out


def unique_key(qid: str, e: dict) -> tuple:
    return (qid, e["kind"], e.get("text"), e.get("source_doc_id"), e.get("source_svo_chunk_index"))


def run(eval_dir: Path = EVAL_DIR) -> dict:
    per_file: dict[str, dict] = {}
    seen: dict[tuple, dict] = {}
    for path in sorted(eval_dir.rglob("records*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = list(iter_trace_entries(data))
        if not entries:
            continue
        per_file[path.relative_to(eval_dir).as_posix()] = summarize(entries)
        if "backup" in path.name:
            continue  # 備份檔與正檔內容重複，不併入去重集合
        for qid, e in entries:
            key = unique_key(qid, e)
            prev = seen.get(key)
            # 同一事實跨多次 run：只要任一次進 prompt 即記為進過（保守描述，不重複計數）
            if prev is None:
                seen[key] = {"qid": qid, "e": e, "ever_in_prompt": e.get("in_prompt") is True}
            elif e.get("in_prompt") is True:
                prev["ever_in_prompt"] = True
    unique = summarize((v["qid"], {**v["e"], "in_prompt": v["ever_in_prompt"]}) for v in seen.values())
    return {"per_file": per_file, "unique_union": unique,
            "replayable_marks": ["article_no", "in_prompt"],
            "not_replayable": ["fields", "relation_type", "subject_type", "object_type"]}


def main() -> None:
    result = run()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    u = result["unique_union"]
    print(f"來源檔 {len(result['per_file'])} 個；去重後題數 {u['questions']}")
    for kind, k in u["by_kind"].items():
        print(kind, {x: v for x, v in k.items()})


if __name__ == "__main__":
    main()
