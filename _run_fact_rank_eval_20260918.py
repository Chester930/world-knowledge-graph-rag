"""Scratch driver for the AGGR15-17 Fact ranking pilot.

Variants:
  dense_selected_k: dense retrieval with per-question final Fact budgets
                    (AGGR15/17=10, AGGR16=25).
  hybrid_rrf:       existing dense + CJK full-text RRF fusion, final top_k=20.

The production modules are monkeypatched only in this process. No source code,
KG records, or global defaults are changed by this driver.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

VARIANT = os.environ.get("FACT_RANK_VARIANT", "").strip()
OUT_DIR = Path(os.environ.get("FACT_RANK_OUT", "")).resolve()
VALID_VARIANTS = {"dense_selected_k", "hybrid_rrf"}
if VARIANT not in VALID_VARIANTS:
    raise SystemExit(f"FACT_RANK_VARIANT must be one of {sorted(VALID_VARIANTS)}")
if not os.environ.get("FACT_RANK_OUT"):
    raise SystemExit("FACT_RANK_OUT must point to a new, unique output directory")
if OUT_DIR.exists() and any(OUT_DIR.iterdir()):
    raise SystemExit(f"Refusing to overwrite non-empty output directory: {OUT_DIR}")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SOURCE_DATASET = ROOT / "data" / "eval" / "test_cases.json"
selected_ids = {"57-AGGR15", "57-AGGR16", "57-AGGR17"}
dataset = json.loads(SOURCE_DATASET.read_text(encoding="utf-8"))
selected = [q for q in dataset["questions"] if q["id"] in selected_ids]
if {q["id"] for q in selected} != selected_ids:
    raise SystemExit("The source dataset does not contain exactly the requested cases")
subset = {key: value for key, value in dataset.items() if key != "questions"}
subset["questions"] = selected
questions_path = OUT_DIR / "questions.json"
questions_path.write_text(
    json.dumps(subset, ensure_ascii=False, indent=2), encoding="utf-8"
)

TOP_K_BY_QUESTION = {
    "《職業安全衛生管理辦法》的法源依據是什麼？": 10,
    "《職業安全衛生管理辦法》規定的第一類事業與第二類事業，風險等級與應設置管理單位的人數門檻各是什麼？": 25,
    "《職業安全衛生管理辦法》將第一類、第二類及第三類事業各自歸為何種風險等級？": 10,
}
if VARIANT == "dense_selected_k" and len(TOP_K_BY_QUESTION) != len(selected):
    raise SystemExit("Per-question top_k mapping does not cover all selected cases")

experiment_config = {
    "variant": VARIANT,
    "question_ids": sorted(selected_ids),
    "kg_id": "236903cf-055a-40a8-8923-b9d06601f3b7",
    "doc_ids": [
        "N0060027_職業安全衛生管理辦法",
        "N0060001_職業安全衛生法",
    ],
    "runs": 3,
    "query_timeout_s": 900,
    "allow_shared_judge": True,
    "retrieval": (
        {
            "hybrid": False,
            "final_top_k_by_question": TOP_K_BY_QUESTION,
            "note": "dense-only; retrieval final budget follows report 57 §4.13 candidates",
        }
        if VARIANT == "dense_selected_k"
        else {
            "hybrid": True,
            "final_top_k": 20,
            "candidate_multiplier": 4,
            "note": "existing dense + CJK full-text RRF, no new reranker dependency",
        }
    ),
    "production_code_modified": False,
    "neo4j_fact_data_writes_expected": False,
    "neo4j_fulltext_index_may_be_ensured": VARIANT == "hybrid_rrf",
    "baseline_dense_top_k_20_scope_on_n3": {
        "57-AGGR15": {
            "context_recall_pct": 100.0,
            "atomic_accuracy_pct": 50.0,
            "snr_pct": 10.54,
            "context_tokens": 254,
            "latency_median_s": 34.99,
        },
        "57-AGGR16": {
            "context_recall_pct": 100.0,
            "atomic_accuracy_pct": 25.0,
            "snr_pct": 9.97,
            "context_tokens": 263,
            "latency_median_s": 599.75,
        },
        "57-AGGR17": {
            "context_recall_pct": 100.0,
            "atomic_accuracy_pct": 100.0,
            "snr_pct": 4.86,
            "context_tokens": 246,
            "latency_median_s": 524.06,
        },
        "source": "report 57 §4.13 / report 60 §1.4; K scope-on, n=3",
    },
    "evaluation_success_criteria": [
        "All 9 records complete without harness error or timeout.",
        "Per-question median Context Recall and Atomic Accuracy do not fall below the scope-on dense top_k=20 baseline.",
        "For dense_selected_k, median context tokens decrease by at least 15% on AGGR15 and AGGR17, with no worse Context Recall or Atomic Accuracy.",
        "For hybrid_rrf, at least one of SNR or Context Recall improves on a target question without an Atomic Accuracy decrease; median latency increase must remain within 20% of baseline.",
        "These are pilot gates for choosing follow-up experiments, not production rollout criteria.",
    ],
}
(OUT_DIR / "experiment_config.json").write_text(
    json.dumps(experiment_config, ensure_ascii=False, indent=2), encoding="utf-8"
)

import routers.agent as agent  # noqa: E402

_real_chat = agent.chat
_real_vector_search_facts = agent.vector_search_facts
_current = {"question": None}


async def _patched_vector_search_facts(driver, kg_id, query_vector, top_k, **kwargs):
    if VARIANT == "hybrid_rrf":
        kwargs["hybrid"] = True
        kwargs["question"] = _current["question"]
    return await _real_vector_search_facts(
        driver, kg_id, query_vector, top_k=top_k, **kwargs
    )


async def _patched_chat(payload):
    _current["question"] = payload.question
    if VARIANT == "dense_selected_k":
        if payload.question not in TOP_K_BY_QUESTION:
            raise RuntimeError("Unexpected question in dense_selected_k arm")
        payload = payload.model_copy(
            update={"top_k": TOP_K_BY_QUESTION[payload.question]}
        )
    return await _real_chat(payload)


agent.vector_search_facts = _patched_vector_search_facts
agent.chat = _patched_chat

print(
    f"[fact-rank-eval] variant={VARIANT} questions={len(selected)} out={OUT_DIR}",
    file=sys.stderr,
)

sys.argv = [
    "run_rq1_comparison.py",
    "--kg-id",
    "236903cf-055a-40a8-8923-b9d06601f3b7",
    "--doc-ids",
    "N0060027_職業安全衛生管理辦法,N0060001_職業安全衛生法",
    "--questions",
    str(questions_path),
    "--arms",
    "K",
    "--runs",
    "3",
    "--query-timeout-s",
    "900",
    "--allow-shared-judge",
    "--out",
    str(OUT_DIR),
]

from scripts.eval.run_rq1_comparison import main  # noqa: E402

main()
