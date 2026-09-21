"""報告62 §12.3 生成階段失敗診斷：重放候選 prompt 並逐步縮減雜訊行（唯讀，不動 KG）。

從候選 records 取出某題**實際進 prompt 的事實行**（T0 trace 的 `prompt_context_lines`），
用與 `chat()` 相同的 `_build_prompt()` 模板重放，再依條件改變 context：

  full     完整 prompt 行（重放，確認失敗可重現且是否決定性）
  first18  只留前 18 行
  first10  只留前 10 行
  relevant 只留含 gold span 或含指定關鍵字的行（oracle 最小 context）
  reversed 行序反轉（gold 由最前移到最後，檢查位置敏感度）

判定用簡單標記（答案是否含指定答案字串、是否含「未明確記載／無法確認」），**不是**正式
AtomicScorer 分數，只用來看行為是否翻轉。用法：
  python scripts/eval/diagnose_prompt_noise.py --qid 18-Q4 --answer-marker 一百五十 \
      --answer-marker 150 --keep-keyword 召集 --repeats 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
for _k, _v in {
    "WORKSPACE_DIR": "D:/Users/666/Desktop/kg-runtime",
    "NEO4J_URI": "bolt://localhost:17990",
    "NEO4J_PASSWORD": "kg2_test_2026",
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
}.items():
    os.environ.setdefault(_k, _v)

from core.providers.factory import get_llm_provider, init_providers  # noqa: E402
from routers import agent  # noqa: E402

DATA = REPO_ROOT / "data" / "eval"
STAGES = [
    "t2_k1_topk40_stage_a", "t2_k1_topk40_stage_a2", "t2_k1_topk40_stage_a3", "t2_k1_topk40_stage_b",
    "t2_k1_topk40_stage_b2a", "t2_k1_topk40_stage_b2b", "t2_k1_topk40_stage_b2c", "t2_k1_topk40_stage_c",
]
REFUSAL_MARKERS = ("資料未明確記載", "無法確認", "未明確記載")


def _clean(s: str) -> str:
    return "".join(s.split())


def load_record(qid: str) -> dict:
    for stage in STAGES:
        for r in json.loads((DATA / "candidate_runs" / stage / "records.json").read_text(encoding="utf-8")):
            if r["question_id"] == qid and not r.get("error"):
                return r
    raise SystemExit(f"找不到 {qid} 的有效候選紀錄")


def build_conditions(lines: list[str], gold: list[str], keywords: list[str]) -> dict[str, list[str]]:
    gold_c = [_clean(g) for g in gold]
    relevant = [
        ln for ln in lines
        if any(g in _clean(ln) for g in gold_c) or any(k in ln for k in keywords)
    ]
    return {
        "full": list(lines),
        "first18": lines[:18],
        "first10": lines[:10],
        "relevant": relevant,
        "reversed": list(reversed(lines)),
    }


async def generate(llm, prompt: str) -> str:
    return "".join([tok async for tok in llm.stream(prompt)]).strip()


async def main_async(args: argparse.Namespace) -> None:
    rec = load_record(args.qid)
    bank = {q["id"]: q for q in json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))["questions"]}
    tc = bank[args.qid]
    gold = [f["exact_span"] for f in tc["atomic_gold_facts"]]
    sets = rec["lineage"]["stage2_context"]["prompt_context_lines"]
    if len(sets) != 1:
        raise SystemExit(f"{args.qid} 是複合問題（{len(sets)} 份 prompt），此腳本只支援單一問題")
    lines = sets[0]
    conds = build_conditions(lines, gold, args.keep_keyword or [])
    init_providers()
    llm = get_llm_provider()
    print(f"{args.qid}: {tc['question']}\n原候選 prompt {len(lines)} 行；條件行數 "
          f"{ {k: len(v) for k, v in conds.items()} }\n", flush=True)
    results = []
    for name, cl in conds.items():
        prompt = await agent._build_prompt(tc["question"], [], [], None, embedding_provider=None, context_lines=cl)
        answers = [await generate(llm, prompt) for _ in range(args.repeats)]
        for i, ans in enumerate(answers, 1):
            has = any(m in ans for m in args.answer_marker)
            refuses = any(m in ans for m in REFUSAL_MARKERS)
            results.append({"condition": name, "lines": len(cl), "run": i, "has_answer": has,
                            "refuses": refuses, "answer": ans})
            print(f"[{name:9s} n={len(cl):2d} run{i}] has_answer={has!s:5s} refuses={refuses!s:5s} | "
                  f"{ans[:90].replace(chr(10), ' ')}", flush=True)
        print("  determinism:", "identical" if len(set(answers)) == 1 else "differs", flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--qid", required=True)
    p.add_argument("--answer-marker", action="append", default=[], required=True,
                   help="答案含任一字串即視為答出（可重複）")
    p.add_argument("--keep-keyword", action="append", help="relevant 條件額外保留含此關鍵字的行")
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--out")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
