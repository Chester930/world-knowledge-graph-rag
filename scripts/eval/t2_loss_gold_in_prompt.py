"""報告62 §12：退步題的 gold span 是否在候選 prompt 內（唯讀，子字串比對，近似）。"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "data" / "eval"
CAND = ROOT / "candidate_runs"
stages = ["t2_k1_topk40_stage_a", "t2_k1_topk40_stage_a2", "t2_k1_topk40_stage_a3", "t2_k1_topk40_stage_b",
          "t2_k1_topk40_stage_b2a", "t2_k1_topk40_stage_b2b", "t2_k1_topk40_stage_b2c", "t2_k1_topk40_stage_c"]
bank = {q["id"]: q for q in json.load(open(ROOT / "test_cases.json", encoding="utf-8"))["questions"]}


def clean(s):
    return "".join(s.split())


for qid in ["57-DIST1", "57-DIST2", "18-Q4"]:
    tc = bank[qid]
    gold = [f["exact_span"] for f in tc["atomic_gold_facts"]]
    r = next(x for s in stages for x in json.load(open(CAND / s / "records.json", encoding="utf-8"))
             if x["question_id"] == qid and not x.get("error"))
    st1, st2 = r["lineage"]["stage1_retrieval"], r["lineage"]["stage2_context"]
    tr = st1["retrieval_trace"]
    prompt_text = clean("".join("".join(ls) for ls in st2["prompt_context_lines"]))
    print("=" * 8, qid, "| prompt line sets", [len(x) for x in st2["prompt_context_lines"]])
    for g in gold:
        in_prompt = clean(g) in prompt_text
        in_retrieved = [e for e in tr if clean(g) in clean(e["text"])]
        print(f" gold: {g[:50]}...")
        print(f"   substring in prompt lines: {in_prompt} | in retrieved trace entries: {[(e['kind'], e['rank'], e['in_prompt']) for e in in_retrieved]}")
    print(" judge hit:", [h[:30] for h in st1["hit_exact_spans"]], "| judge missed:", [m[:30] for m in st1["missed_exact_spans"]])
    print(" retained_after_stage2(retrieved-basis):", [h[:30] for h in st2["retained_exact_spans"]])
