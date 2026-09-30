"""KG 來源回取「召回優先」離線探測（報告155 T5；任務書_KG來源回取召回優先探測_v0.1）。

唯讀、離線：不呼叫 LLM／embedding、不連 Neo4j、不重跑 K 或 B1。只讀凍結記錄、B1 索引與 KG 資料夾
（``svo_index.json``）。召回判定**重用** ``services.lineage_tracker.LineageTracker.record_retrieval``
（嚴格逐字比對，去空白／換行；不含語意 fallback，因為 fallback 需要 LLM）。

**不得以 gold exact_span 參與任何選段**：R1 的取捨只依 K 候選的排名與去重（及 B1 字元預算）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from models.eval_schema import AtomicGoldFact  # noqa: E402
from services.classify_service import resolve_document_folder  # noqa: E402
from services.document_record_service import document_uuid  # noqa: E402
from services.lineage_tracker import LineageTracker  # noqa: E402
from services.svo_chunking import read_svo_index  # noqa: E402

BASE = REPO / "data" / "eval" / "baseline_runs" / "20260923_rebased"
K_DIRS = [BASE / "stage_s0_r1", BASE / "stage_s0_r1_resume1"]  # 42 題 run 1
K_R2_DIR = BASE / "stage_s0_r2"  # 第二批（敏感度用）
B1_DIR = REPO / "data" / "eval" / "candidate_runs" / "s3_chunk_rag_b1_stage_a"
B1_INDEX = REPO / "baseline_rag_index_236903cf-055a-40a8-8923-b9d06601f3b7_cs500.json"
BANK = REPO / "docs" / "附錄A題庫.json"
DEFAULT_KG = Path("D:/Users/666/Desktop/kg-runtime/236903cf-055a-40a8-8923-b9d06601f3b7")
OUT = REPO / "data" / "eval" / "candidate_runs" / "kg_source_recall_probe"
M_VALUES = (3, 5, 8)


def strip_len(text: str) -> int:
    return len(text.replace(" ", "").replace("\n", ""))


# ── 來源解析器（T1）────────────────────────────────────────────────────


@dataclass
class Resolution:
    ok: bool
    reason: str  # ok 時為 via（article_no／chunk_index），否則為失敗原因
    doc_id: str | None = None
    chunk_index: int | None = None
    text: str = ""


class SourceResolver:
    """把 K 的 retrieval_trace 候選對應到 KG 資料夾內的來源 chunk 文字（唯讀）。"""

    def __init__(self, kg_folder: Path):
        self.kg_folder = Path(kg_folder)
        self._doc_by_uuid = {
            str(document_uuid(d.name)): d.name
            for d in sorted(self.kg_folder.iterdir())
            if d.is_dir() and not d.name.startswith("_")
        }
        self._index_cache: dict[str, dict | None] = {}

    def _svo_index(self, doc_id: str) -> dict | None:
        if doc_id not in self._index_cache:
            self._index_cache[doc_id] = read_svo_index(resolve_document_folder(self.kg_folder, doc_id))
        return self._index_cache[doc_id]

    def resolve(self, cand: dict) -> Resolution:
        sdi = cand.get("source_doc_id")
        if not sdi:
            return Resolution(False, "no_source_doc_id")
        doc_id = self._doc_by_uuid.get(str(sdi))
        if doc_id is None:
            return Resolution(False, "doc_not_found")
        idx = self._svo_index(doc_id)
        if idx is None:
            return Resolution(False, "svo_index_missing", doc_id)
        chunks = idx.get("chunks", [])
        article_no = cand.get("article_no")
        if article_no:
            for c in chunks:
                if c.get("article_no") == article_no:
                    return Resolution(True, "article_no", doc_id, c["index"], c.get("text", ""))
        ci = cand.get("source_svo_chunk_index")
        if ci is None:
            return Resolution(False, "no_chunk_index", doc_id)
        for c in chunks:
            if c["index"] == ci:
                return Resolution(True, "chunk_index", doc_id, ci, c.get("text", ""))
        return Resolution(False, "chunk_index_not_found", doc_id, ci)


def dedup_sources(cands: list[dict], resolver: SourceResolver) -> tuple[list[dict], list[dict]]:
    """依 K 排名順序解析候選；同一 (doc, chunk) 只留首次出現。回傳 (段落清單, 無法解析清單)。"""
    seen: set[tuple[str, int]] = set()
    paragraphs: list[dict] = []
    unresolved: list[dict] = []
    for cand in cands:
        res = resolver.resolve(cand)
        if not res.ok:
            unresolved.append({"kind": cand.get("kind"), "rank": cand.get("rank"), "reason": res.reason,
                               "source_doc_id": cand.get("source_doc_id"), "in_prompt": cand.get("in_prompt")})
            continue
        key = (res.doc_id, res.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        paragraphs.append({"doc_id": res.doc_id, "chunk_index": res.chunk_index, "text": res.text,
                           "first_rank": cand.get("rank"), "first_kind": cand.get("kind"),
                           "first_in_prompt": cand.get("in_prompt"), "via": res.reason})
    return paragraphs, unresolved


def take_by_budget(paragraphs: list[dict], budget: int) -> list[dict]:
    out, total = [], 0
    for p in paragraphs:
        n = strip_len(p["text"])
        if total + n > budget:
            break
        out.append(p)
        total += n
    return out


# ── 召回量測（重用 LineageTracker）────────────────────────────────────


def measure(texts: list[str], gold: list[str], atomic: list[AtomicGoldFact]) -> dict:
    lin = LineageTracker("probe", "probe", "").record_retrieval(
        texts, gold, latency_ms=0.0, atomic_gold_facts=atomic)
    return {"recall_rate": lin.recall_rate, "hit": lin.hit_exact_spans, "missed": lin.missed_exact_spans,
            "char_count": lin.retrieved_char_count, "snr": lin.snr}


def load_bank(path: Path = BANK) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for q in data["questions"]:
        atomic = [AtomicGoldFact(**f) for f in q.get("atomic_gold_facts", [])]
        out[q["id"]] = {"scenario_type": q.get("scenario_type"), "atomic": atomic,
                        "gold": [f.exact_span for f in atomic]}
    return out


def load_records(dirs: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in dirs:
        for r in json.loads((d / "records.json").read_text(encoding="utf-8")):
            cur = out.get(r["question_id"])
            if cur is None or r.get("run", 1) < cur.get("run", 1):
                out[r["question_id"]] = r
    return out


def load_b1_index(path: Path = B1_INDEX) -> dict[tuple[str, int], str]:
    return {(c["source"], c["chunk_index"]): c["chunk_text"] for c in json.loads(path.read_text(encoding="utf-8"))}


def b1_texts(rec: dict, index: dict) -> tuple[list[str], list[str]]:
    texts, missing = [], []
    for cid in rec["lineage"]["stage1_retrieval"]["retrieved_chunk_ids"]:
        source, _, ci = cid.rpartition("_")
        t = index.get((source, int(ci)))
        if t is None:
            missing.append(cid)
        else:
            texts.append(t)
    return texts, missing


# ── 主流程 ────────────────────────────────────────────────────────────


def run_question(qid: str, krec: dict, brec: dict | None, bank: dict, resolver: SourceResolver,
                 b1_index: dict) -> dict:
    q = bank[qid]
    gold, atomic = q["gold"], q["atomic"]
    trace = krec["lineage"]["stage1_retrieval"]["retrieval_trace"]
    s1 = krec["lineage"]["stage1_retrieval"]
    faces: dict[str, dict] = {}

    all_texts = [e["text"] for e in trace]
    prompt_texts = [e["text"] for e in trace if e["in_prompt"]]
    faces["R0_all"] = measure(all_texts, gold, atomic)
    faces["R0_prompt"] = measure(prompt_texts, gold, atomic)
    faces["R0_all"]["recorded_recall"] = s1["recall_rate"]
    faces["R0_all"]["recorded_char_count"] = s1["retrieved_char_count"]

    facts = sorted((e for e in trace if e["kind"] == "fact"), key=lambda e: e["rank"])
    paragraphs, unresolved = dedup_sources(facts, resolver)
    # 全部候選（含 triple）的無法解析統計
    _, unresolved_all = dedup_sources(sorted(trace, key=lambda e: (e["kind"], e["rank"])), resolver)
    prompt_facts = [e for e in facts if e["in_prompt"]]
    para_prompt, _ = dedup_sources(prompt_facts, resolver)

    for m in M_VALUES:
        faces[f"R1_m{m}"] = measure([p["text"] for p in paragraphs[:m]], gold, atomic)
        faces[f"R1_m{m}"]["paragraphs"] = [(p["doc_id"], p["chunk_index"]) for p in paragraphs[:m]]
    faces["R1_prompt_m5"] = measure([p["text"] for p in para_prompt[:5]], gold, atomic)

    b1_char = None
    if brec is not None:
        bt, missing = b1_texts(brec, b1_index)
        faces["R2"] = measure(bt, gold, atomic)
        faces["R2"]["recorded_recall"] = brec["lineage"]["stage1_retrieval"]["recall_rate"]
        faces["R2"]["recorded_char_count"] = brec["lineage"]["stage1_retrieval"]["retrieved_char_count"]
        faces["R2"]["chunk_ids"] = brec["lineage"]["stage1_retrieval"]["retrieved_chunk_ids"]
        faces["R2"]["missing_chunks"] = missing
        b1_char = brec["lineage"]["stage1_retrieval"]["retrieved_char_count"]
        picked = take_by_budget(paragraphs, b1_char)
        faces["R1_budget"] = measure([p["text"] for p in picked], gold, atomic)
        faces["R1_budget"]["paragraphs"] = [(p["doc_id"], p["chunk_index"]) for p in picked]
        faces["R1_budget"]["budget"] = b1_char

    # R3：R0_prompt ∪ R1_m5（事實清單＋來源段落）
    faces["R3_prompt_plus_m5"] = measure(prompt_texts + [p["text"] for p in paragraphs[:5]], gold, atomic)

    reasons = Counter(u["reason"] for u in unresolved_all)
    return {
        "question_id": qid,
        "scenario_type": q["scenario_type"],
        "gold_span_count": len(gold),
        "k_perfect": krec.get("atomic_score", {}).get("is_perfect"),
        "n_candidates": len(trace),
        "n_in_prompt": len(prompt_texts),
        "n_unique_source_paragraphs": len(paragraphs),
        "unresolved_by_reason": dict(reasons),
        "unresolved": unresolved_all,
        "paragraph_sources": [{k: v for k, v in p.items() if k != "text"} for p in paragraphs],
        "faces": faces,
    }


def signals(krec: dict) -> dict:
    trace = krec["lineage"]["stage1_retrieval"]["retrieval_trace"]
    inp = [e for e in trace if e["in_prompt"]]
    top20 = sorted(trace, key=lambda e: (e["kind"], e["rank"]))[:20]
    n_tri = sum(1 for e in inp if e["kind"] == "triple")
    return {
        "distinct_docs_in_prompt": len({e["source_doc_id"] for e in inp}),
        "distinct_docs_top20": len({e["source_doc_id"] for e in top20}),
        "triple_share_in_prompt": round(n_tri / len(inp), 4) if inp else None,
        "n_in_prompt": len(inp),
    }


def aggregate(rows: list[dict], face: str) -> dict:
    vals = [r["faces"][face] for r in rows if face in r["faces"]]
    if not vals:
        return {}
    return {
        "n": len(vals),
        "mean_recall": round(statistics.mean(v["recall_rate"] for v in vals), 4),
        "recall_eq_1": sum(1 for v in vals if v["recall_rate"] == 1.0),
        "mean_chars": round(statistics.mean(v["char_count"] for v in vals), 1),
        "mean_snr": round(statistics.mean(v["snr"] for v in vals), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kg-folder", type=Path, default=DEFAULT_KG)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    bank = load_bank()
    resolver = SourceResolver(a.kg_folder)
    b1_index = load_b1_index()
    krecs = load_records(K_DIRS)
    brecs = load_records([B1_DIR])
    rows = [run_question(qid, krecs[qid], brecs.get(qid), bank, resolver, b1_index) for qid in sorted(krecs)]
    for r in rows:
        r["signals"] = signals(krecs[r["question_id"]])

    faces = sorted({f for r in rows for f in r["faces"]})
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["scenario_type"]].append(r)
    summary = {"all": {f: aggregate(rows, f) for f in faces},
               "by_type": {t: {f: aggregate(rs, f) for f in faces} for t, rs in sorted(by_type.items())},
               "n_questions": len(rows)}

    # R2 敏感度：第二批 K（33 題）
    k2 = load_records([K_R2_DIR])
    rows2 = [run_question(qid, k2[qid], brecs.get(qid), bank, resolver, b1_index) for qid in sorted(k2)]
    summary["sensitivity_r2_batch"] = {f: aggregate(rows2, f) for f in faces}

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "per_question.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    un = [{"question_id": r["question_id"], "scenario_type": r["scenario_type"], "by_reason": r["unresolved_by_reason"],
           "items": r["unresolved"]} for r in rows]
    (a.out / "unresolved_candidates.json").write_text(json.dumps(un, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary["all"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
