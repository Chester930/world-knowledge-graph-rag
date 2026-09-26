"""報告82：GAP-S3-01 最小上下文組裝消融（唯讀，不接線 production）。

對報告78 的五個 Stage 3 生成端案例，把 B1 實際取回且包含目標 gold span
的最高順位原始 chunk，附加到 S0 K arm 已保存的 prompt context lines，
以同一個生成 provider 重複生成兩次，再用 AtomicScorer.evaluate() 做離線
逐字評分。此腳本不連線 Neo4j，也不呼叫 routers.agent.chat()。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.providers.factory import get_llm_provider, init_providers  # noqa: E402
from models.eval_schema import EvaluationDataset  # noqa: E402
from routers import agent  # noqa: E402
from services.atomic_scorer import AtomicScorer  # noqa: E402


DATA = REPO_ROOT / "data" / "eval"
S0_STAGE = "baseline_runs/20260923_rebased/stage_s0_r1"
B1_STAGE = "candidate_runs/s3_chunk_rag_b1_stage_a"
INDEX_PATH = REPO_ROOT / "baseline_rag_index_236903cf-055a-40a8-8923-b9d06601f3b7_cs500.json"
TARGET_IDS = ["18-Q1", "18-Q6", "57-AGGR14", "57-COREF3", "57-DIST2"]
DEFAULT_OUT = DATA / "candidate_runs" / "gap_s3_01_context_ablation.json"


def _read_records(relative_dir: str) -> list[dict[str, Any]]:
    path = DATA / relative_dir / "records.json"
    return [r for r in json.loads(path.read_text(encoding="utf-8")) if not r.get("error")]


def _load_index() -> dict[str, dict[str, Any]]:
    rows = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {f"{row['source']}_{row['chunk_index']}": row for row in rows}


def _find_record(records: list[dict[str, Any]], question_id: str) -> dict[str, Any]:
    matches = [r for r in records if r.get("question_id") == question_id]
    if len(matches) != 1:
        raise ValueError(f"{question_id}: expected one record, got {len(matches)}")
    return matches[0]


def _select_chunk(
    b1_record: dict[str, Any],
    target_span: str,
    index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chunk_ids = b1_record["lineage"]["stage1_retrieval"]["retrieved_chunk_ids"]
    candidates = []
    for rank, chunk_id in enumerate(chunk_ids, start=1):
        row = index.get(chunk_id)
        if row is None:
            raise ValueError(f"B1 chunk {chunk_id!r} not found in {INDEX_PATH.name}")
        if target_span in row["chunk_text"]:
            candidates.append((rank, chunk_id, row))
    if not candidates:
        raise ValueError(f"{b1_record['question_id']}: no B1 chunk contains target span")
    rank, chunk_id, row = candidates[0]
    return {
        "rank": rank,
        "chunk_id": chunk_id,
        "source": row["source"],
        "chunk_index": row["chunk_index"],
        "chunk_text": row["chunk_text"],
        "candidate_count_containing_span": len(candidates),
    }


def _score(answer: str, test_case: Any) -> dict[str, Any]:
    result = AtomicScorer.evaluate(
        answer,
        test_case.atomic_gold_facts,
        refusal_expected=False,
        deterministic_guard_passed=True,
        trap_claim_spans=test_case.trap_claim_spans,
    )
    return result.model_dump()


def _augmentation_lines(chunk: dict[str, Any]) -> list[str]:
    return [
        "=== 依據法規原文段落 ===",
        f"【參考段落】（來源：{chunk['source']}_{chunk['chunk_index']}）",
        chunk["chunk_text"],
    ]


async def _generate_once(
    test_case: Any,
    k_record: dict[str, Any],
    chunk: dict[str, Any],
    llm: Any,
) -> tuple[str, list[dict[str, Any]]]:
    original_sets = k_record["lineage"]["stage2_context"]["prompt_context_lines"]
    sub_questions = agent._split_into_subquestions(test_case.question)
    if len(original_sets) != len(sub_questions):
        raise ValueError(
            f"{test_case.id}: prompt set count {len(original_sets)} != "
            f"subquestion count {len(sub_questions)}"
        )

    augmented = _augmentation_lines(chunk)
    parts: list[str] = []
    prompts: list[dict[str, Any]] = []
    for index, (sub_question, original_lines) in enumerate(
        zip(sub_questions, original_sets, strict=True), start=1
    ):
        augmented_lines = list(original_lines) + augmented
        prompt = await agent._build_prompt(
            sub_question,
            [],
            [],
            history=None,
            embedding_provider=None,
            cfg=None,
            context_lines=augmented_lines,
        )
        tokens = [token async for token in llm.stream(prompt)]
        answer = "".join(tokens).strip()
        parts.append(f"{index}. {sub_question}\n{answer}")
        prompts.append(
            {
                "sub_question": sub_question,
                "original_fact_line_count": len(original_lines),
                "augmented_context_line_count": len(augmented_lines),
                "augmentation_repeated_for_subquestion": True,
            }
        )
    return "\n\n".join(parts), prompts


def _prepare_cases() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dataset = EvaluationDataset.model_validate(
        json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))
    )
    questions = {question.id: question for question in dataset.questions}
    s0_records = _read_records(S0_STAGE)
    b1_records = _read_records(B1_STAGE)
    index = _load_index()
    cases = []
    for question_id in TARGET_IDS:
        test_case = questions[question_id]
        k_record = _find_record(s0_records, question_id)
        b1_record = _find_record(b1_records, question_id)
        missing = k_record["atomic_score"]["missing_spans"]
        if len(missing) != 1:
            raise ValueError(f"{question_id}: expected one target missing span, got {missing}")
        target_span = missing[0]
        chunk = _select_chunk(b1_record, target_span, index)
        cases.append(
            {
                "question_id": question_id,
                "question": test_case.question,
                "target_missing_span": target_span,
                "baseline": {
                    "stage": S0_STAGE,
                    "is_perfect": k_record["atomic_score"]["is_perfect"],
                    "missing_spans": k_record["atomic_score"]["missing_spans"],
                    "supported_spans": k_record["atomic_score"]["supported_spans"],
                    "answer": k_record["answer"],
                    "answer_char_count": len(k_record["answer"]),
                },
                "b1_source": {
                    "stage": B1_STAGE,
                    "is_perfect": b1_record["atomic_score"]["is_perfect"],
                    "retrieved_chunk_ids": b1_record["lineage"]["stage1_retrieval"][
                        "retrieved_chunk_ids"
                    ],
                    "selected_chunk": chunk,
                },
                "runs": [],
            }
        )
    return cases, questions


def _write(path: Path, cases: list[dict[str, Any]], status: str) -> None:
    payload = {
        "description": "報告82 T1-T5：S0 K + 一個 B1 原始法規段落的最小上下文消融",
        "status": status,
        "parameters": {
            "model": "qwen2.5:7b",
            "provider": "ollama",
            "repeats_per_question": 2,
            "target_question_ids": TARGET_IDS,
            "s0_stage": S0_STAGE,
            "b1_stage": B1_STAGE,
            "index": INDEX_PATH.name,
            "scorer": "services.atomic_scorer.AtomicScorer.evaluate",
            "neo4j_access": False,
            "chat_endpoint_access": False,
            "paragraphs_added_per_question": 1,
        },
        "cases": cases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


async def _run(args: argparse.Namespace) -> None:
    cases, questions = _prepare_cases()
    out = Path(args.out)
    _write(out, cases, "running")
    init_providers()
    llm = get_llm_provider()
    model = getattr(llm, "model", None)
    if model != "qwen2.5:7b":
        raise RuntimeError(f"configured generator model is {model!r}, expected 'qwen2.5:7b'")
    for case in cases:
        test_case = questions[case["question_id"]]
        k_record = _find_record(_read_records(S0_STAGE), case["question_id"])
        for run_index in range(1, 3):
            answer, prompt_meta = await _generate_once(
                test_case, k_record, case["b1_source"]["selected_chunk"], llm
            )
            score = _score(answer, test_case)
            target_supported = case["target_missing_span"] in score["supported_spans"]
            case["runs"].append(
                {
                    "run": run_index,
                    "answer": answer,
                    "answer_char_count": len(answer),
                    "atomic_score": score,
                    "target_span_supported": target_supported,
                    "prompt_subquestions": prompt_meta,
                }
            )
            _write(out, cases, "running")
            print(
                f"{case['question_id']} run{run_index}: "
                f"is_perfect={score['is_perfect']} target_supported={target_supported} "
                f"missing={len(score['missing_spans'])} chars={len(answer)}",
                flush=True,
            )
    _write(out, cases, "complete")
    print(f"saved {out}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
