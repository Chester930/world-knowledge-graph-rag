"""報告62 §14（T5）：評分器判定與確定性文字重疊指標的不一致篩選（唯讀）。

`AtomicScorer` 對 gold span 的判定（逐字命中，否則用 LLM judge 做語意蘊含）沒有獨立
真值可對照。這裡用**與 LLM judge 無關**的字元 bigram 召回（gold span 的 bigram 有多少比例
出現在答案）當「文字重疊」代理指標，找出兩類值得人工審讀的案例：

  fn_candidate  評分器判 missing、但答案與 gold 高度重疊（可能是偽陰性，例如改寫）
  fp_candidate  評分器判 supported、但答案與 gold 重疊很低（可能是偽陽性，例如語意過寬鬆）

另抽兩組一致案例（agree_hit／agree_miss）當對照。**代理指標不是真值**：高重疊也可能屬於
歸屬錯置或否定句，低重疊也可能是合理改寫，所以輸出只是「審讀名單」，最終判定要人工。
只看 Type-E 以外的題目（拒答題的 gold 是「未記載」類，另案處理）。

用法：python scripts/eval/audit_scorer_disagreements.py --out <dir> [--seed 20260922]
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "eval"
BASE_STAGES = ["stage_a", "stage_a2", "stage_b3", "stage_b4", "stage_b5", "stage_b6", "stage_b7"]
CAND_STAGES = [
    "t2_k1_topk40_stage_a", "t2_k1_topk40_stage_a2", "t2_k1_topk40_stage_a3", "t2_k1_topk40_stage_b",
    "t2_k1_topk40_stage_b2a", "t2_k1_topk40_stage_b2b", "t2_k1_topk40_stage_b2c", "t2_k1_topk40_stage_c",
]
_PUNCT = re.compile(r"[\s，。、；：「」『』（）()\[\]【】,.;:!?！？\-—*#>`'\"“”]+")


def norm(s: str) -> str:
    return _PUNCT.sub("", s or "")


def bigrams(s: str) -> set[str]:
    t = norm(s)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def overlap(gold: str, answer: str) -> float:
    g = bigrams(gold)
    return len(g & bigrams(answer)) / len(g) if g else 0.0


def best_window(gold: str, answer: str, width: int = 140) -> str:
    """答案中與 gold bigram 重疊最多的片段（供人工審讀）。"""
    a = re.sub(r"\s+", " ", answer)
    g = bigrams(gold)
    best, best_i = -1, 0
    for i in range(0, max(len(a) - width, 0) + 1, 20):
        sc = len(g & bigrams(a[i:i + width]))
        if sc > best:
            best, best_i = sc, i
    return a[best_i:best_i + width]


def load(stages_root: str, stages: list[str]) -> list[dict]:
    out = []
    for st in stages:
        p = DATA / stages_root / st / "records.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text(encoding="utf-8")):
            if not r.get("error"):
                r["_arm"] = "base" if stages_root == "baseline_runs/20260920_frozen" else "cand"
                r["_stage"] = st
                out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20260922)
    ap.add_argument("--n-fn", type=int, default=20)
    ap.add_argument("--n-fp", type=int, default=20)
    ap.add_argument("--n-agree", type=int, default=8)
    args = ap.parse_args()

    bank = {q["id"]: q for q in json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))["questions"]}
    records = load("baseline_runs/20260920_frozen", BASE_STAGES) + load("candidate_runs", CAND_STAGES)
    rows = []
    for r in records:
        tc = bank[r["question_id"]]
        if tc["scenario_type"] == "Type-E":
            continue
        a = r["atomic_score"]
        supported, missing = set(a.get("supported_spans") or []), set(a.get("missing_spans") or [])
        for f in tc["atomic_gold_facts"]:
            span = f["exact_span"]
            if span in supported:
                verdict = "supported"
            elif span in missing:
                verdict = "missing"
            else:
                continue
            rows.append({
                "question_id": r["question_id"], "arm": r["_arm"], "stage": r["_stage"], "type": tc["scenario_type"],
                "gold_span": span, "scorer": verdict, "overlap": round(overlap(span, r["answer"]), 3),
                "window": best_window(span, r["answer"]), "question": tc["question"][:70],
            })
    print("gold-span judgements (Type-E excluded):", len(rows))
    for v in ("supported", "missing"):
        xs = [x["overlap"] for x in rows if x["scorer"] == v]
        print(f"  scorer={v}: n={len(xs)} mean overlap={sum(xs) / max(len(xs), 1):.3f}")

    fn = [x for x in rows if x["scorer"] == "missing" and x["overlap"] >= 0.7]
    fp = [x for x in rows if x["scorer"] == "supported" and x["overlap"] < 0.5]
    ah = [x for x in rows if x["scorer"] == "supported" and x["overlap"] >= 0.7]
    am = [x for x in rows if x["scorer"] == "missing" and x["overlap"] < 0.4]
    print(f"fn_candidates={len(fn)} fp_candidates={len(fp)} agree_hit={len(ah)} agree_miss={len(am)}")
    rnd = random.Random(args.seed)
    sample = []
    for name, pool, n in (("fn_candidate", fn, args.n_fn), ("fp_candidate", fp, args.n_fp),
                          ("agree_hit", ah, args.n_agree), ("agree_miss", am, args.n_agree)):
        for x in rnd.sample(pool, min(n, len(pool))):
            sample.append({**x, "group": name, "group_size": len(pool)})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "all_span_judgements.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for i, x in enumerate(sample):
        x["id"] = i
    (out / "review_sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", len(sample), "review cases to", out)


if __name__ == "__main__":
    main()
