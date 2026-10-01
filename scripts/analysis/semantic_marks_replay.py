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


# ── 唯讀 join（報告217 §8，使用者已授權選項 A）：以 (source_doc_id, chunk_index, fact_text) 對回 Fact ──
_FACT_QUERY = (
    "MATCH (f:Fact {kg_id: $k}) "
    "OPTIONAL MATCH (f)-[:SUPPORTED_BY]->(a:LawArticle) "
    "RETURN f.source_doc_id AS doc, f.source_svo_chunk_index AS idx, f.fact_text AS text, "
    "f.subject AS subject, f.object AS object, f.verb AS verb, f.rel_type AS rel_type, "
    "a.article_no AS article_no"
)


def fetch_fact_table(runner, kg_id: str) -> list[dict]:
    """唯讀取出 KG 全部 Fact（約 1.7 萬筆）。`runner` 須為 `ReadOnlyRunner`（白名單＋READ session）。"""
    return runner.run("M2 join：Fact 全表", _FACT_QUERY, k=kg_id)


def build_fact_index(rows: Iterable[dict]) -> dict[tuple, list[dict]]:
    """鍵＝(doc, chunk_index, text)；同鍵可能多筆（KG#4 有 225 組重複鍵），保留全部以便偵測歧義。"""
    docs_with_article: set[str] = set()
    for r in rows:
        if sm.has_article_no(r.get("article_no")):
            docs_with_article.add(str(r.get("doc")))
    index: dict[tuple, list[dict]] = {}
    for r in rows:
        applicable = str(r.get("doc")) in docs_with_article
        marks = {
            "fields": sm.mark_fact_fields(r.get("subject"), r.get("object"), r.get("verb")),
            "relation_type": sm.mark_relation_type(r.get("rel_type")),
            "article_no": sm.mark_article_no(r.get("article_no"), applicable),
        }
        key = (str(r.get("doc")), r.get("idx"), r.get("text"))
        index.setdefault(key, []).append(marks)
    return index


def join_summarize(entries: Iterable[tuple[str, dict]], index: dict[tuple, list[dict]]) -> dict:
    """只處理 kind=fact。被檢索 vs 進 prompt（in_prompt is True）各標示計數；
    未對到／鍵重複且標示不一致者另計（不猜測）。"""
    out = {"fact_entries": 0, "matched": 0, "unmatched": 0, "ambiguous": 0,
           "retrieved": {"fields": Counter(), "relation_type": Counter(), "article_no": Counter()},
           "in_prompt": {"fields": Counter(), "relation_type": Counter(), "article_no": Counter()},
           "in_prompt_matched": 0}
    for _qid, e in entries:
        if e.get("kind") != "fact":
            continue
        out["fact_entries"] += 1
        cands = index.get((str(e.get("source_doc_id")), e.get("source_svo_chunk_index"), e.get("text")))
        if not cands:
            out["unmatched"] += 1
            continue
        if any(c != cands[0] for c in cands[1:]):
            out["ambiguous"] += 1
            continue
        out["matched"] += 1
        for name, mark in cands[0].items():
            out["retrieved"][name][mark] += 1
            if e.get("in_prompt") is True:
                out["in_prompt"][name][mark] += 1
        if e.get("in_prompt") is True:
            out["in_prompt_matched"] += 1
    for grp in ("retrieved", "in_prompt"):
        out[grp] = {k: dict(v) for k, v in out[grp].items()}
    return out


def run_join(runner, kg_id: str, eval_dir: Path = EVAL_DIR) -> dict:
    index = build_fact_index(fetch_fact_table(runner, kg_id))
    per_file: dict[str, dict] = {}
    for path in sorted(eval_dir.rglob("records*.json")):
        if "backup" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = list(iter_trace_entries(data))
        if entries:
            per_file[path.relative_to(eval_dir).as_posix()] = join_summarize(entries, index)
    return {"per_file": per_file, "fact_index_keys": len(index)}


def main_join(argv: list[str]) -> int:
    import argparse
    import re

    ap = argparse.ArgumentParser()
    ap.add_argument("--join-neo4j", action="store_true")
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    from neo4j import GraphDatabase
    from scripts.analysis.semantic_layer_invariants import (
        BOLT_URI_DEFAULT, EXPECTED_TOTALS, KG_ID_DEFAULT, ReadOnlyRunner, totals,
    )

    def env(key: str) -> str | None:  # 不修改 os.environ、不輸出值
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*)$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
        return None

    password = env("NEO4J_PASSWORD")
    if not password:
        raise SystemExit("需要 .env 的 NEO4J_PASSWORD")
    driver = GraphDatabase.driver(BOLT_URI_DEFAULT, auth=(env("NEO4J_USER") or "neo4j", password))
    try:
        runner = ReadOnlyRunner(driver)
        before = totals(runner, KG_ID_DEFAULT, "before")
        if before != EXPECTED_TOTALS:
            raise SystemExit(f"資料量與預期不符，停止：{before}")
        result = run_join(runner, KG_ID_DEFAULT)
        after = totals(runner, KG_ID_DEFAULT, "after")
        if after != before:
            raise SystemExit(f"唯讀前後總數不一致：{before} -> {after}")
    finally:
        driver.close()
    result.update({"before": before, "after": after, "totals_identical": before == after,
                   "cypher_log": runner.log})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"totals_identical": result["totals_identical"], "before": before,
                      "files": len(result["per_file"])}, ensure_ascii=False))
    return 0


def main() -> None:
    if "--join-neo4j" in sys.argv:
        raise SystemExit(main_join(sys.argv[1:]))
    result = run()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    u = result["unique_union"]
    print(f"來源檔 {len(result['per_file'])} 個；去重後題數 {u['questions']}")
    for kind, k in u["by_kind"].items():
        print(kind, {x: v for x, v in k.items()})


if __name__ == "__main__":
    main()
