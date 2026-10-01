"""報告223 O1：「條文子句被當實體名稱」的唯讀量化（只量化、不處理）。

**「像子句」是操作型定義，不是語意判定**（見 `FEATURES` 與 `LEGAL_NAME_RE` 的誤判風險說明）：
以名稱**長度門檻**（預設 ≥8／≥12／≥20）為主，輔以條文用語、標點、數字＋單位等**字面特徵**；不使用 LLM。

結構：**純運算**（門檻、特徵、彙整、近似重複、檢索交叉）與 **DB 存取**（只收 `ReadOnlyRunner`）分離。
本模組匯入時不連線、不讀環境變數、不改 `os.environ`、不呼叫 LLM／embedding；不寫 KG。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis import semantic_marks_replay_join as rj  # noqa: E402
from scripts.analysis.semantic_marks_replay import EVAL_DIR, iter_trace_entries  # noqa: E402
from services import semantic_marks as sm  # noqa: E402

THRESHOLDS = (8, 12, 20)
MAIN_THRESHOLD = 12
CONCEPT = sm.CONCEPT_PLACEHOLDER

# 條文用語（含「不得」「視為」等雙字詞；「得」「之」「其」單字誤判風險最高）
KEYWORDS = ("者", "之", "應", "得", "不得", "視為", "以上", "未滿", "其", "前項")
_PUNCT_RE = re.compile(r"[，、,；;（）()「」『』：:]")
_NUM = r"[0-9０-９一二三四五六七八九十百千萬零〇兩]+"
_NUM_UNIT_RE = re.compile(_NUM + r"\s*(?:日|天|年|月|週|周|星期|小時|分鐘|元|人|歲|倍|%|％|成|次|項|款|條)")
# 疑似合法長名稱：以法規／機構用語結尾，或「…法第N條」式條文引用（啟發式，會漏判也會誤判）
LEGAL_NAME_RE = re.compile(
    r"(?:法|條例|辦法|細則|標準|規則|準則|規程|要點|通則|綱要|公約|協定)"
    r"(?:第[0-9一二三四五六七八九十百零〇]+條(?:之[0-9一二三四五六七八九十]+)?(?:第[0-9一二三四五六七八九十]+[項款])?)?$"
)

FEATURES = {
    "條文用語": lambda n: any(k in n for k in KEYWORDS),
    "標點括號": lambda n: _PUNCT_RE.search(n) is not None,
    "數字加單位": lambda n: _NUM_UNIT_RE.search(n) is not None,
}


# ── 純運算 ────────────────────────────────────────────────────────────────────
def name_features(name: str) -> dict[str, bool]:
    return {label: bool(fn(name)) for label, fn in FEATURES.items()}


def is_strong_candidate(name: str, threshold: int = MAIN_THRESHOLD) -> bool:
    """長度達門檻且至少一項字面特徵——「強候選」。仍是字面規則：合法長名稱（如施行細則第三十五條）會被誤判。"""
    return len(name) >= threshold and any(name_features(name).values())


def is_legal_name_like(name: str) -> bool:
    return LEGAL_NAME_RE.search(name) is not None


def quantiles(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {k: None for k in ("min", "p25", "median", "p75", "p90", "p99", "max")}
    s = sorted(values)

    def pick(p: float) -> float:
        i = (len(s) - 1) * p
        lo = int(i)
        hi = min(lo + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (i - lo)

    return {"min": s[0], "p25": pick(0.25), "median": pick(0.5), "p75": pick(0.75),
            "p90": pick(0.9), "p99": pick(0.99), "max": s[-1]}


_BINS = ((1, 3), (4, 7), (8, 11), (12, 19), (20, 39), (40, 10**9))


def histogram(values: Iterable[int]) -> dict[str, int]:
    out = {(f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"): 0 for lo, hi in _BINS}
    out["0"] = 0
    for v in values:
        if v <= 0:
            out["0"] += 1
            continue
        for lo, hi in _BINS:
            if lo <= v <= hi:
                out[f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"] += 1
                break
    return out


def _share(n: int, total: int) -> float | None:
    return n / total if total else None


def threshold_summary(entities: list[dict], thresholds: Iterable[int] = THRESHOLDS) -> dict[str, Any]:
    """各長度門檻：總數／占比、概念 vs 非概念、各特徵命中、強候選、疑似合法長名稱。"""
    total = len(entities)
    n_concept = sum(1 for e in entities if e["type"] == CONCEPT)
    out: dict[str, Any] = {"entities": total, "concept_entities": n_concept,
                           "length": quantiles([len(e["name"]) for e in entities]),
                           "histogram": histogram(len(e["name"]) for e in entities), "by_threshold": {}}
    for th in thresholds:
        grp = [e for e in entities if len(e["name"]) >= th]
        concept = [e for e in grp if e["type"] == CONCEPT]
        feats = Counter()
        for e in grp:
            for label, hit in name_features(e["name"]).items():
                feats[label] += hit
        strong = [e for e in grp if any(name_features(e["name"]).values())]
        out["by_threshold"][str(th)] = {
            "count": len(grp), "share_of_all": _share(len(grp), total),
            "concept": len(concept), "share_of_concept_entities": _share(len(concept), n_concept),
            "non_concept": len(grp) - len(concept),
            "share_of_non_concept_entities": _share(len(grp) - len(concept), total - n_concept),
            "features": dict(feats), "strong_candidates": len(strong),
            "legal_name_like": sum(1 for e in grp if is_legal_name_like(e["name"])),
        }
    return out


def type_marks(entities: Iterable[dict], core: Mapping[str, str], ext: Mapping[str, str]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = {s: Counter() for s in sm.CONCEPT_SCHEMES}
    for e in entities:
        for s in sm.CONCEPT_SCHEMES:
            out[s][sm.mark_entity_type(e["type"], core, ext, s)] += 1
    return {s: dict(c) for s, c in out.items()}


def degrees_and_docs(edge_rows: Iterable[dict]) -> tuple[dict[str, int], dict[str, set[str]]]:
    """度數＝事實邊入＋出（自環計 2，同報告214）；文件數＝端點所有邊引用的不同 `source_doc_id`。"""
    degree: Counter = Counter()
    docs: dict[str, set[str]] = {}
    for r in edge_rows:
        s, o = r.get("subject"), r.get("object")
        degree[s] += 1
        degree[o] += 1
        for c in rj._parse(r.get("citations_json")):
            d = c.get("source_doc_id")
            if d:
                docs.setdefault(s, set()).add(str(d))
                docs.setdefault(o, set()).add(str(d))
    return dict(degree), docs


def degree_doc_summary(names: Iterable[str], degree: Mapping[str, int], docs: Mapping[str, set[str]]) -> dict[str, Any]:
    names = list(names)
    deg = [degree.get(n, 0) for n in names]
    dc = [len(docs.get(n, ())) for n in names]
    n = len(names)
    return {
        "entities": n,
        "degree_quantiles": quantiles(deg),
        "degree_hist": {"0": sum(d == 0 for d in deg), "1": sum(d == 1 for d in deg), "2": sum(d == 2 for d in deg),
                        "3-5": sum(3 <= d <= 5 for d in deg), "6+": sum(d >= 6 for d in deg)},
        "degree_eq_1_share": _share(sum(d == 1 for d in deg), n),
        "doc_count_hist": {"0": sum(d == 0 for d in dc), "1": sum(d == 1 for d in dc), "2+": sum(d >= 2 for d in dc)},
        "single_doc_share": _share(sum(d == 1 for d in dc), n),
    }


def affected_facts(names: set[str], fact_rows: Iterable[dict]) -> dict[str, Any]:
    """以集合內實體當主詞或受詞的 Fact 數與占比。"""
    rows = list(fact_rows)
    subj = sum(1 for r in rows if r.get("subject") in names)
    obj = sum(1 for r in rows if r.get("object") in names)
    either = sum(1 for r in rows if r.get("subject") in names or r.get("object") in names)
    return {"facts_total": len(rows), "as_subject": subj, "as_object": obj, "either": either,
            "either_share": _share(either, len(rows))}


def normalize_for_dedupe(name: str) -> str:
    """去除標點、空白與符號後逐字比對（不做相似度模型）；保守：只合併僅標點／空白不同者。"""
    return "".join(ch for ch in name if unicodedata.category(ch)[0] not in ("P", "Z", "S", "C"))


def near_duplicates(names: Iterable[str]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(normalize_for_dedupe(n), []).append(n)
    dup = {k: v for k, v in groups.items() if len(v) > 1}
    return {"entities": sum(len(v) for v in groups.values()), "groups": len(groups), "duplicate_groups": len(dup),
            "entities_in_duplicate_groups": sum(len(v) for v in dup.values()),
            "examples": [v[:3] for v in list(dup.values())[:5]],
            "bias_note": "只比對去除標點／空白後完全相同；實體名稱在 KG 內唯一，故只會抓到標點差異，其餘近似重複皆漏計（保守偏低）。"}


def cross_retrieval(entries: Iterable[tuple[str, dict]], fact_index: dict, edge_index: dict, sets: Mapping[str, set[str]]) -> dict[str, Any]:
    """被檢索／進 prompt 的 Fact／triple 中，端點含「像子句」實體者的計數。

    對回沿用 `semantic_marks_replay_join` 的索引（索引需以 `extra_fields=("subject","object")` 建立）；
    未對到或歧義者不計入（與報告218 相同處理）。
    """
    out: dict[str, Any] = {}
    for _qid, e in entries:
        kind = e.get("kind")
        if kind not in ("fact", "triple"):
            continue
        s = out.setdefault(kind, {"entries": 0, "matched": 0, "retrieved": Counter(), "in_prompt": Counter(),
                                  "matched_in_prompt": 0})
        s["entries"] += 1
        if kind == "fact":
            cands = fact_index.get((str(e.get("source_doc_id")), e.get("source_svo_chunk_index"), e.get("text")))
        else:
            cands = rj._edge_candidates(edge_index, e)
        if not cands or any((c["subject"], c["object"]) != (cands[0]["subject"], cands[0]["object"]) for c in cands[1:]):
            continue
        s["matched"] += 1
        ip = e.get("in_prompt") is True
        s["matched_in_prompt"] += ip
        for label, names in sets.items():
            if cands[0]["subject"] in names or cands[0]["object"] in names:
                s["retrieved"][label] += 1
                s["in_prompt"][label] += ip
    for s in out.values():
        s["retrieved"], s["in_prompt"] = dict(s["retrieved"]), dict(s["in_prompt"])
    return out


# ── DB 存取（只收 ReadOnlyRunner）─────────────────────────────────────────────
def fetch_entities(runner, kg_id: str) -> list[dict]:
    return runner.run("O1：Entity 名稱與型別", "MATCH (e:Entity {kg_id: $k}) RETURN e.name AS name, e.type AS type", k=kg_id)


def collect(runner, kg_id: str, core: Mapping[str, str], ext: Mapping[str, str], eval_dir: Path = EVAL_DIR) -> dict:
    entities = [{"name": r["name"] or "", "type": r["type"] or ""} for r in fetch_entities(runner, kg_id)]
    fact_rows = rj.fetch_facts(runner, kg_id)
    edge_rows = rj.fetch_edges(runner, kg_id)
    degree, docs = degrees_and_docs(edge_rows)

    sets: dict[str, set[str]] = {}
    for th in THRESHOLDS:
        sets[f"len>={th}"] = {e["name"] for e in entities if len(e["name"]) >= th}
    sets[f"strong(len>={MAIN_THRESHOLD}+特徵)"] = {e["name"] for e in entities if is_strong_candidate(e["name"])}

    result: dict[str, Any] = {"summary": threshold_summary(entities), "groups": {}}
    for label, names in sets.items():
        grp = [e for e in entities if e["name"] in names]
        result["groups"][label] = {
            "count": len(grp),
            "type_marks": type_marks(grp, core, ext),
            "degree_docs": degree_doc_summary(names, degree, docs),
            "affected_facts": affected_facts(names, fact_rows),
            "near_duplicates": near_duplicates(names),
        }
    result["baseline_all_entities"] = {
        "type_marks": type_marks(entities, core, ext),
        "degree_docs": degree_doc_summary({e["name"] for e in entities}, degree, docs),
    }

    fact_index = rj.build_fact_index(fact_rows, core, ext, extra_fields=("subject", "object"))
    edge_index = rj.build_edge_index(edge_rows, core, ext, extra_fields=("subject", "object"))
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
            per_file[path.relative_to(eval_dir).as_posix()] = cross_retrieval(entries, fact_index, edge_index, sets)
    result["retrieval_cross_per_file"] = per_file
    result["_pools"] = {"entities": entities, "edge_rows": edge_rows}  # 供 O2 抽樣使用；寫檔前移除
    return result


def _env_value(env_file: Path, key: str) -> str | None:
    """讀單一 .env 值；不改 os.environ、不輸出。"""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        m = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def open_runner(env_file: Path):
    """建立 READ session 的 `ReadOnlyRunner`；密碼只從 `.env` 取、不輸出。回傳 (driver, runner)。"""
    from neo4j import GraphDatabase  # noqa: PLC0415
    from scripts.analysis.semantic_layer_invariants import BOLT_URI_DEFAULT, ReadOnlyRunner  # noqa: PLC0415

    password = _env_value(env_file, "NEO4J_PASSWORD")
    if not password:
        raise SystemExit("需要 .env 的 NEO4J_PASSWORD")
    driver = GraphDatabase.driver(BOLT_URI_DEFAULT, auth=(_env_value(env_file, "NEO4J_USER") or "neo4j", password))
    return driver, ReadOnlyRunner(driver)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="O1 彙總 JSON")
    ap.add_argument("--pool-out", type=Path, required=True, help="O2 抽樣用母體 JSON（≥12 字 Entity＋其邊；不含密碼）")
    args = ap.parse_args(argv)
    from scripts.analysis.semantic_layer_invariants import EXPECTED_TOTALS, KG_ID_DEFAULT, totals  # noqa: PLC0415
    from services.context.trace_marks import load_type_lookups  # noqa: PLC0415

    core, ext = load_type_lookups()
    driver, runner = open_runner(args.env_file)
    try:
        before = totals(runner, KG_ID_DEFAULT, "before")
        if before != EXPECTED_TOTALS:
            raise SystemExit(f"資料量與預期不符，停止：{before}")
        result = collect(runner, KG_ID_DEFAULT, core, ext)
        after = totals(runner, KG_ID_DEFAULT, "after")
        if after != before:
            raise SystemExit(f"唯讀前後總數不一致：{before} -> {after}")
    finally:
        driver.close()
    pools = result.pop("_pools")
    long_names = {e["name"] for e in pools["entities"] if len(e["name"]) >= MAIN_THRESHOLD}
    pool = {
        "entities": [e for e in pools["entities"] if e["name"] in long_names],
        "edges": [{"subject": r["subject"], "object": r["object"], "rel_type": r["rel_type"],
                   "citations": r["citations_json"]}
                  for r in pools["edge_rows"] if r["subject"] in long_names or r["object"] in long_names],
    }
    result.update({"before": before, "after": after, "totals_identical": before == after,
                   "cypher_log": runner.log, "definition": {
                       "thresholds": list(THRESHOLDS), "main_threshold": MAIN_THRESHOLD, "keywords": list(KEYWORDS),
                       "features": list(FEATURES), "legal_name_re": LEGAL_NAME_RE.pattern}})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.pool_out.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"totals_identical": result["totals_identical"], "before": before,
                      "groups": {k: v["count"] for k, v in result["groups"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
