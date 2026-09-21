"""報告62 §11／§12：K1（top_k=40）對凍結基準的採用判定分析（唯讀）。

依 §11.1 預先宣告的規則產出：達標題數配對、退步檢查、SNR、Type-E、配對統計
（exact McNemar、bootstrap、配對差 95% CI）與 T0 trace 拆解。基準判定用
`baseline_runs/20260920_frozen/summary_final.json`，候選用
`candidate_runs/t2_k1_topk40_stage_c/summary_final.json`。
執行：python scripts/eval/t2_topk40_judgement.py
"""
import json
import math
import pathlib
import random
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2] / "data" / "eval"
BASE = ROOT / "baseline_runs/20260920_frozen"
CAND = ROOT / "candidate_runs"
bank = {q["id"]: q for q in json.load(open(ROOT / "test_cases.json", encoding="utf-8"))["questions"]}
eligible = json.load(open(BASE / "frozen_manifest.json", encoding="utf-8"))["eligible_ids"]

base_sum = json.load(open(BASE / "summary_final.json", encoding="utf-8"))["questions"]
cand_sum = json.load(open(CAND / "t2_k1_topk40_stage_c/summary_final.json", encoding="utf-8"))["questions"]


def passed(entry):
    st, vr = entry["status"], entry["valid_results"]
    if st in ("stable_pass", "single_pass"):
        return True
    if st in ("stable_fail",):
        return False
    return sum(vr) * 2 > len(vr)  # unstable → majority


bp = {q: passed(base_sum[q]) for q in eligible}
cp = {q: passed(cand_sum[q]) for q in eligible}
print("baseline pass:", sum(bp.values()), "| candidate pass:", sum(cp.values()), "| n =", len(eligible))

gains = [q for q in eligible if cp[q] and not bp[q]]
losses = [q for q in eligible if bp[q] and not cp[q]]
print("GAINS  (cand pass, base fail):", gains)
print("LOSSES (base pass, cand fail):", losses)
print("net:", len(gains) - len(losses))

# regression: baseline STABLE pass now stable fail
reg = [q for q in eligible if base_sum[q]["status"] == "stable_pass" and cand_sum[q]["status"] == "stable_fail"]
print("baseline stable_pass -> candidate stable_fail:", reg)
print("baseline single_pass -> candidate stable_fail:",
      [q for q in eligible if base_sum[q]["status"] == "single_pass" and cand_sum[q]["status"] == "stable_fail"])

# ---- paired statistics
d = [int(cp[q]) - int(bp[q]) for q in eligible]
n = len(d)
mean = sum(d) / n
se = statistics.stdev(d) / math.sqrt(n)
print(f"paired diff mean={mean:+.4f}  SE={se:.4f}  95% CI=({mean - 1.96 * se:+.4f}, {mean + 1.96 * se:+.4f})")
# exact McNemar (two-sided sign test) on discordant pairs
b, c = len(gains), len(losses)
m = b + c
if m:
    k = min(b, c)
    p = min(1.0, 2 * sum(math.comb(m, i) for i in range(0, k + 1)) / 2 ** m)
else:
    p = 1.0
print(f"discordant: gains={b} losses={c}  exact McNemar two-sided p={p:.4f}")
random.seed(20260921)
boots = []
for _ in range(10000):
    s = [d[random.randrange(n)] for _ in range(n)]
    boots.append(sum(s))
boots.sort()
print("bootstrap net-count 95% CI:", boots[250], boots[9749])

# ---- metrics from records (per-question mean over valid runs, then mean over questions)
def load_records(paths):
    out = {}
    for p in paths:
        for r in json.load(open(p, encoding="utf-8")):
            if r.get("error"):
                continue
            out.setdefault(r["question_id"], []).append(r)
    return out


base_paths = [BASE / s / "records.json" for s in ["stage_a", "stage_a2", "stage_b3", "stage_b4", "stage_b5", "stage_b6", "stage_b7"]]
cand_paths = [CAND / s / "records.json" for s in [
    "t2_k1_topk40_stage_a", "t2_k1_topk40_stage_a2", "t2_k1_topk40_stage_a3", "t2_k1_topk40_stage_b",
    "t2_k1_topk40_stage_b2a", "t2_k1_topk40_stage_b2b", "t2_k1_topk40_stage_b2c", "t2_k1_topk40_stage_c"]]
BR, CR = load_records(base_paths), load_records(cand_paths)


def qmean(recs, f):
    vals = [f(r) for r in recs if f(r) is not None]
    return sum(vals) / len(vals) if vals else None


def agg(R, f, qs):
    per = [qmean(R[q], f) for q in qs if q in R]
    per = [x for x in per if x is not None]
    return (sum(per) / len(per), len(per)) if per else (None, 0)


snr = lambda r: r["lineage"]["stage1_retrieval"]["snr"]
rec = lambda r: r["lineage"]["stage1_retrieval"]["recall_rate"]
acc = lambda r: r["atomic_score"]["atomic_accuracy"]
chars = lambda r: r["lineage"]["stage1_retrieval"]["retrieved_char_count"]
chain = lambda r: r["lineage"]["stage1_retrieval"]["chain_completeness"]
print("\n--- metrics (question-level mean of run means, n questions)")
for name, f in [("Recall", rec), ("SNR", snr), ("AtomicAcc", acc), ("retrieved_chars", chars), ("chain_completeness", chain)]:
    bv, bn = agg(BR, f, eligible)
    cv, cn = agg(CR, f, eligible)
    print(f"{name:20s} base={bv:.4f} (n={bn})  cand={cv:.4f} (n={cn})")

# SNR floor rule: cand SNR >= 0.5 * base SNR
bs_, _ = agg(BR, snr, eligible)
cs_, _ = agg(CR, snr, eligible)
print(f"SNR ratio cand/base = {cs_ / bs_:.3f}  (floor 0.5)")

# Type-E
te = [q for q in eligible if bank[q]["scenario_type"] == "Type-E"]
print("\nType-E questions:", len(te), "| base pass", sum(bp[q] for q in te), "| cand pass", sum(cp[q] for q in te))
print("  Type-E changes:", [(q, bp[q], cp[q]) for q in te if bp[q] != cp[q]])

# by scenario type
print("\n--- pass by scenario type (base -> cand)")
types = sorted({bank[q]["scenario_type"] for q in eligible})
for t in types:
    qs = [q for q in eligible if bank[q]["scenario_type"] == t]
    print(f"{t}: n={len(qs)} base={sum(bp[q] for q in qs)} cand={sum(cp[q] for q in qs)}")

# ---- trace decomposition (candidate only; baseline has no trace)
print("\n--- trace decomposition (candidate runs with trace)")
tot = dict(f_in=0, f_late_in=0, bfs_in=0, bfs_all=0, runs=0, prompt_lines=0)
for q, recs_ in CR.items():
    for r in recs_:
        tr = r["lineage"]["stage1_retrieval"].get("retrieval_trace") or []
        if not tr:
            continue
        facts = [e for e in tr if e["kind"] == "fact"]
        trip = [e for e in tr if e["kind"] == "triple"]
        tot["runs"] += 1
        tot["f_in"] += sum(1 for e in facts if e["in_prompt"])
        tot["f_late_in"] += sum(1 for e in facts if e["in_prompt"] and e["rank"] >= 20)
        tot["bfs_in"] += sum(1 for e in trip if e["in_prompt"])
        tot["bfs_all"] += len(trip)
        tot["prompt_lines"] += sum(len(x) for x in r["lineage"]["stage2_context"]["prompt_context_lines"])
runs = max(tot["runs"], 1)
print({k: (round(v / runs, 2) if k != "runs" else v) for k, v in tot.items()})

# For gain/loss questions: did hit spans come from rank>=20 facts in prompt?
def clean(s):
    return s.replace(" ", "").replace("\n", "")


print("\n--- per gain/loss question: candidate hit spans found in prompt facts rank>=20 (substring, approximate)")
for q in gains + losses:
    label = "GAIN" if q in gains else "LOSS"
    for r in CR.get(q, [])[:1]:
        st1 = r["lineage"]["stage1_retrieval"]
        tr = st1.get("retrieval_trace") or []
        late = [e for e in tr if e["kind"] == "fact" and e["in_prompt"] and e["rank"] >= 20]
        early = [e for e in tr if e["kind"] == "fact" and e["in_prompt"] and e["rank"] < 20]
        gold = [f["exact_span"] for f in bank[q]["atomic_gold_facts"]]
        in_late = [g for g in gold if any(clean(g) in clean(e["text"]) for e in late)]
        in_early = [g for g in gold if any(clean(g) in clean(e["text"]) for e in early)]
        bfs_in = sum(1 for e in tr if e["kind"] == "triple" and e["in_prompt"])
        brec = qmean(BR[q], rec)
        print(f"{label} {q}: recall base={brec:.2f} cand={qmean(CR[q], rec):.2f} | gold {len(gold)}: substr-in-rank<20={len(in_early)} rank>=20={len(in_late)} | bfs_in_prompt={bfs_in}")
