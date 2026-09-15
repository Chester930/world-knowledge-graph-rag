"""離線重評分腳本（報告52 後續修正）。

背景：報告52（`rq1_eval_results/sample_expansion_20260915/`，10題×4arm×3run=
120筆）發現 `services/atomic_scorer.py`／`services/lineage_tracker.py` 用
「gold exact_span 逐字子字串比對」判定命中，對報告24自然語言化管線改寫過
用詞的 Fact-RAG/KG 答案（M3/M4）系統性低估——17-Q1 案例回答內容完全正確，
卻因未逐字複製法規句式被判失敗。本腳本用 `services/semantic_span_matcher.py`
新增的語意 NLI fallback，離線重新評分既有 120 筆資料，不重新呼叫
`agent.chat()`、不重新檢索、不需要 Neo4j 寫入。

範圍（使用者已裁示，見 `docs/報告/` 後續補述）：
- **Stage 3**（答案 vs gold span）：`answer` 文字完整存在 `run{n}.json`，
  全部題目全部 arm 都重新評分——這是本次修正最主要的效果來源，直接對應
  報告52 Pareto 表的 atomic_accuracy／atomic_recall。
- **Stage 1/2**（檢索原文 vs gold span）：只有 M1/M2（chunk-RAG baseline）
  的 `retrieved_chunk_ids` 完整可用，能用本機 baseline 索引查回原文重評。
  M3/M4 的 `retrieved_fact_ids`／BFS 三元組 `natural_text` 在這批舊資料裡
  全部是空字串——根因是 `routers/agent.py::_serialize_sources()` 舊版
  序列化遺漏 `fact_id`／`natural_text` 兩個欄位（本次已修好，見
  `routers/agent.py` 改動與 `tests/routers/test_agent.py` 對應測試），但
  無法回溯修補已經落盤的舊 120 筆資料。M3/M4 的 Stage1/2/failure_attribution
  維持原判定，只更新 Stage3 的 atomic_score，並標註 `rescore_note` 誠實
  說明限制。

執行環境：只需 Ollama（judge LLM，`--judge-model` 預設沿用 manifest 記錄的
`llm_model`）＋本機 baseline 索引檔（`build_baseline_chunk_index.py` 產物）。
不連 Neo4j，不寫入任何資料庫。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.providers.factory import get_judge_llm_provider, get_llm_provider, init_providers
from services import baseline_rag_service
from services.atomic_scorer import AtomicScorer
from services.semantic_span_matcher import match_spans_with_fallback

from scripts.eval.run_rq1_comparison import (  # noqa: E402  (需先設好 sys.path)
    ARM_ALIAS_MAP,
    _load_questions,
    _render_pareto_summary,
)


def _build_chunk_text_lookup(kg_id: str, chunk_size: int) -> dict[str, str]:
    from uuid import UUID

    _, meta = baseline_rag_service.load_baseline_index(UUID(kg_id), chunk_size)
    return {f"{m['source']}_{m['chunk_index']}": m["chunk_text"] for m in meta}


async def _rescore_record(
    rec: dict,
    tc_map: dict,
    chunk_lookup: dict[str, str],
    judge_llm_provider,
) -> dict:
    tc = tc_map.get(rec["question_id"])
    if tc is None or rec.get("error"):
        return rec  # 找不到題目定義或原本就是 harness 失敗紀錄，原樣跳過

    question = tc.question
    refusal_exp = (tc.scenario_type.value == "Type-E")

    # ── Stage 3：answer 永遠可從落盤資料重建，全部 arm 都重評 ──
    original_atomic = rec["atomic_score"]
    new_atomic = await AtomicScorer.evaluate_async(
        rec["answer"], tc.atomic_gold_facts, refusal_expected=refusal_exp,
        judge_llm_provider=judge_llm_provider, question=question,
    )
    rec["atomic_score_original"] = original_atomic
    rec["atomic_score"] = new_atomic.model_dump()

    raw_arm = rec.get("raw_arm") or ARM_ALIAS_MAP.get(rec["arm"], rec["arm"])
    gold_spans = [f.exact_span for f in tc.atomic_gold_facts]

    if raw_arm not in ("B0", "B1") or not rec.get("lineage"):
        rec["rescore_note"] = (
            f"{raw_arm} arm：Stage 1/2/failure_attribution 因舊版 "
            "retrieved_fact_ids／BFS natural_text 序列化缺欄位、無法從落盤"
            "資料重建原文，維持原判定；僅 Stage 3 atomic_score 已重評。"
        )
        return rec

    # ── Stage 1/2：M1/M2 的 chunk_ids 完整可用，用本機索引查回原文重評 ──
    chunk_ids = rec["lineage"]["stage1_retrieval"]["retrieved_chunk_ids"]
    pool_texts = [chunk_lookup[c] for c in chunk_ids if c in chunk_lookup]
    missing_lookup = [c for c in chunk_ids if c not in chunk_lookup]
    pool_text = "\n".join(pool_texts)

    hit1, missed1 = await match_spans_with_fallback(
        pool_text, gold_spans, judge_llm_provider, question=question,
    )
    recall1 = len(hit1) / len(gold_spans) if gold_spans else 1.0
    rec["lineage"]["stage1_retrieval"]["hit_exact_spans"] = hit1
    rec["lineage"]["stage1_retrieval"]["missed_exact_spans"] = missed1
    rec["lineage"]["stage1_retrieval"]["recall_rate"] = round(recall1, 4)

    # B0/B1 沒有獨立的截斷/重排步驟（`context_lines` 直接餵給生成端，見
    # `run_rq1_comparison.py::_run_single_query()`），Stage 2 的輸入原文與
    # Stage 1 完全相同，不必重複呼叫 judge LLM，直接沿用 Stage 1 結果。
    hit2, missed2 = hit1, missed1
    rec["lineage"]["stage2_context"]["retained_exact_spans"] = hit2
    rec["lineage"]["stage2_context"]["dropped_exact_spans"] = missed2

    if missed1:
        attribution = (
            f"Stage 1 Retrieval Failure: {len(missed1)}/{len(gold_spans)} "
            f"gold facts missed ({missed1})"
        )
    elif missed2:
        attribution = (
            f"Stage 2 Assembly Failure: {len(missed2)} gold facts dropped "
            f"in context assembly ({missed2})"
        )
    else:
        # 沿用上面 Stage 3 atomic_score 已算好的 supported_spans，不重複呼叫
        # judge LLM——new_atomic 是對同一份 answer／同一組 gold spans 做的
        # 語意 fallback 核對，結果等價。
        supported_set = set(new_atomic.supported_spans)
        missing_in_answer = [s for s in gold_spans if s not in supported_set]
        if missing_in_answer:
            guard_triggered = rec["lineage"]["stage3_generation"].get(
                "deterministic_guard_triggered", False
            )
            if guard_triggered:
                attribution = (
                    f"Stage 3 Generation Failure (Guard Intercepted): "
                    f"LLM deviated from gold spans {missing_in_answer}; guard triggered."
                )
            else:
                attribution = (
                    "Stage 3 Generation Failure (Intrinsic Hallucination / Smoothing): "
                    f"Facts were present in prompt context, but LLM omitted or smoothed "
                    f"{missing_in_answer}."
                )
        else:
            attribution = "Success: All gold spans preserved across all 3 stages."

    rec["failure_attribution_original"] = rec["failure_attribution"]
    rec["failure_attribution"] = attribution
    rec["rescore_note"] = (
        f"{raw_arm} arm：Stage 1/2/3 皆已用語意 fallback 重評（chunk_ids 查回"
        f"本機 baseline 索引原文）。"
        + (f" ⚠️ {len(missing_lookup)} 個 chunk_id 未能在本機索引查到，pool "
           f"text 可能不完整：{missing_lookup}" if missing_lookup else "")
    )
    return rec


async def _main() -> int:
    parser = argparse.ArgumentParser(description="報告52後續修正：語意NLI fallback離線重評分")
    parser.add_argument("--run-dir", default="rq1_eval_results/sample_expansion_20260915")
    parser.add_argument("--out", default="rq1_eval_results/sample_expansion_20260915_rescored")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    # `_load_questions()` 簽章已隨報告48整合改為只回傳未過濾題目清單（eligibility
    # 過濾移到 `services.evaluation_eligibility.split_eligible_test_cases()`），
    # 這裡本來就要拿全部題目（含 unverified）去對應落盤紀錄的 question_id，
    # 不需要再篩選一次。
    test_cases = _load_questions(manifest["questions_file"], "all")
    tc_map = {tc.id: tc for tc in test_cases}

    init_providers()
    judge = get_judge_llm_provider(get_llm_provider())
    chunk_lookup = _build_chunk_text_lookup(manifest["kg_id"], manifest["chunk_size"])
    print(f"本機 baseline 索引載入：{len(chunk_lookup)} 個 chunk（chunk_size={manifest['chunk_size']}）")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_manifest = dict(manifest)
    out_manifest["rescore_source"] = str(run_dir)
    out_manifest["rescore_method"] = "semantic_span_matcher fallback (報告52後續修正)"
    (out_dir / "manifest.json").write_text(
        json.dumps(out_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    all_records: list[dict] = []
    for run_i in range(1, manifest["runs"] + 1):
        run_file = run_dir / f"run{run_i}.json"
        records = json.loads(run_file.read_text(encoding="utf-8"))
        rescored = []
        for rec in records:
            print(f"  重評 run{run_i} · {rec['question_id']} · {rec['arm']} …", flush=True)
            rescored.append(await _rescore_record(rec, tc_map, chunk_lookup, judge))
        (out_dir / f"run{run_i}.json").write_text(
            json.dumps(rescored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        all_records.extend(rescored)

    arms = manifest["arms"]
    _render_pareto_summary(out_dir, out_manifest, all_records, arms, test_cases)
    print(f"\n完成：{len(all_records)} 筆重評 → {out_dir}/")
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
