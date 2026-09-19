"""RQ1 統一評測 Harness（SDD-2.1 交付物）。

支援：
- 四大核心代表方法（M1: Naive Chunk B0、M2: Hybrid Text B1、M3: Fact Vector F、M4: Full KG K）及消融組（D, G, K-2b）。
- 自動調用 AtomicScorer 執行原子法規真值比對（exact_span 逐字核驗 + 語意 NLI fallback）。
- 全鏈路 LineageTracker 記錄（因果隔離檢索、組裝與生成三階段）。
- 三階段 CostAnalyzer 生命週期成本報告與 Pareto 矩陣產出。

評測入口依 `docs/報告/48_評測管線文獻與調整設計.md` 執行：正式題目資格先過濾，
再由 `test_cases × arms × runs` 迴圈產生逐筆 `records.json` 與 Pareto 摘要。
正式評測預設要求獨立 judge；`--allow-shared-judge` 僅供明確標記的 pilot。

⚠️ **2026-09-15 併入報告55**：`AtomicScorer.evaluate()` 逐字比對對報告24自然
語言化管線改寫過用詞的 Fact-RAG/KG 答案系統性低估（報告52）。本次改用
`AtomicScorer.evaluate_async()`（`services/semantic_span_matcher.py`），逐字
比對失敗才補呼叫本檔案原本就已要求獨立設定的 judge provider 做語意蘊含核對
——與報告48「獨立 judge」的硬性要求天然互補：報告48確保有一個可信、獨立於
生成端的 judge，語意 fallback 正好需要這個 judge 才能運作。deterministic
guard（報告48）與語意 fallback（報告52/55）是兩個獨立的修正維度，互不覆寫
（guard 檢核法律關鍵詞是否被竄改，語意 fallback 只處理 exact_span 逐字比對
的假陰性）。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import settings
from core.database import connect, disconnect, get_driver
from core.kg_config import ConfigLoader, FileConfigSource
from core.providers.factory import (
    get_embedding_provider,
    get_judge_llm_provider,
    get_llm_provider,
    init_providers,
)
from models.document import ChatRequest
from models.eval_schema import AtomicGoldFact, EvaluationDataset, TestCase
from repositories.kg_repo import KGRepository
from routers import agent
from services import baseline_rag_service, document_record_service
from services.atomic_scorer import AtomicScorer
from services.claim_scope_auditor import audit_answer_scope
from services.cost_analyzer import CostAnalyzer
from services.deterministic_guard_service import DeterministicGuardService
from services.evaluation_eligibility import split_eligible_test_cases
from services.evaluation_preflight import run_evaluation_preflight
from services.lineage_tracker import LineageTracker

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_CASES_PATH = REPO_ROOT / "data" / "eval" / "test_cases.json"
LEGACY_TEST_CASES_PATH = REPO_ROOT / "docs" / "附錄A題庫.json"

# 方法名稱別名映射
ARM_ALIAS_MAP = {
    "M1": "B0",
    "M2": "B1",
    "M3": "F",
    "M4": "K",
}
INVERSE_ARM_ALIAS_MAP = {
    "B0": "M1",
    "B1": "M2",
    "F": "M3",
    "K": "M4",
}


class _CountingLLM:
    """計數包裝器"""
    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "stream_calls", 0)
        object.__setattr__(self, "json_calls", 0)

    def reset(self):
        object.__setattr__(self, "stream_calls", 0)
        object.__setattr__(self, "json_calls", 0)

    @property
    def calls(self) -> int:
        return self.stream_calls + self.json_calls

    async def stream(self, prompt: str):
        object.__setattr__(self, "stream_calls", self.stream_calls + 1)
        async for tok in self._inner.stream(prompt):
            yield tok

    async def generate_json(self, prompt: str) -> str:
        object.__setattr__(self, "json_calls", self.json_calls + 1)
        return await self._inner.generate_json(prompt)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_inner"), name)


def _load_questions(spec: str, complexity: str) -> list[TestCase]:
    """載入題庫"""
    path = Path(spec)
    if not path.exists():
        if DEFAULT_TEST_CASES_PATH.exists():
            path = DEFAULT_TEST_CASES_PATH
        else:
            path = LEGACY_TEST_CASES_PATH

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_qs = data["questions"] if isinstance(data, dict) and "questions" in data else data

    selected_ids = None
    if spec and not Path(spec).exists():
        selected_ids = {s.strip() for s in spec.split(",") if s.strip()}

    out: list[TestCase] = []
    for q in raw_qs:
        if isinstance(q, dict):
            qid = q.get("id")
            if selected_ids is not None and qid not in selected_ids:
                continue
            if complexity != "all" and q.get("complexity_bucket") != complexity:
                continue
            # 轉換為 TestCase 物件
            gold_facts = [
                AtomicGoldFact(**f) if isinstance(f, dict) else f
                for f in q.get("atomic_gold_facts", [])
            ]
            q_copy = dict(q)
            q_copy["atomic_gold_facts"] = gold_facts
            out.append(TestCase(**q_copy))
    return out


def _resolve_scope(kg_id: UUID, doc_ids: list[str]) -> tuple[list[UUID], set[str]]:
    """解析指定文件範圍"""
    kg_folder = Path(settings.workspace_dir) / str(kg_id)
    uuids, sources = [], set()
    for entry in doc_ids:
        folder = kg_folder / entry
        rec = document_record_service.read_record(folder) if folder.is_dir() else None
        source = rec.source if rec is not None else entry
        uuids.append(document_record_service.document_uuid(source))
        sources.add(source)
        sources.add(entry)
    return uuids, sources


def _load_scoped_baseline_index(kg_id: UUID, chunk_size: int, sources: set[str]):
    import numpy as np

    vectors, meta = baseline_rag_service.load_baseline_index(kg_id, chunk_size)
    keep = [i for i, m in enumerate(meta) if m.get("source") in sources]
    if not keep:
        raise SystemExit(f"baseline 索引（cs{chunk_size}）未涵蓋目標文件。")
    return np.asarray([vectors[i] for i in keep], dtype=np.float32), [meta[i] for i in keep]


async def _drain_chat(payload: ChatRequest) -> dict:
    resp = await agent.chat(payload)
    answer, sources, grounding, regenerated, error = [], None, None, None, None
    async for chunk in resp.body_iterator:
        if chunk.startswith("event: error"):
            error = json.loads(chunk.split("\n", 1)[1][len("data: "):]).get("message")
        elif chunk.startswith("event: sources"):
            sources = json.loads(chunk.split("\n", 1)[1][len("data: "):])
        elif chunk.startswith("event: grounding"):
            grounding = json.loads(chunk.split("\n", 1)[1][len("data: "):])
        elif chunk.startswith("event: status"):
            st = json.loads(chunk.split("\n", 1)[1][len("data: "):])
            if st.get("phase") == "done":
                regenerated = st.get("regenerated")
        elif chunk.startswith("data: "):
            answer.append(json.loads(chunk[len("data: "):]).get("token", ""))
    return {
        "answer": "".join(answer),
        "error": error,
        "regenerated": regenerated,
        "triples": (sources or {}).get("triples", []),
        "facts": (sources or {}).get("facts", []),
        "grounding": grounding or [],
    }


async def _run_single_query(
    tc: TestCase,
    arm: str,
    kg_id: UUID,
    scope_uuids: list[UUID],
    cfg,
    counting: _CountingLLM,
    judge_counting: _CountingLLM | None,
    baseline_index,
    reranker,
    baseline_top_k: int,
) -> dict:
    counting.reset()
    if judge_counting is not None and judge_counting is not counting:
        judge_counting.reset()
    t0 = time.perf_counter()

    raw_arm = ARM_ALIAS_MAP.get(arm, arm)
    tracker = LineageTracker(tc.id, arm, tc.question)
    gold_spans = [f.exact_span for f in tc.atomic_gold_facts]

    context_lines = []
    retrieved_texts = []
    chunk_ids = []
    fact_ids = []

    if raw_arm == "D":
        r = await _drain_chat(ChatRequest(question=tc.question, kg_id=kg_id, use_svo=False))
    elif raw_arm in ("B0", "B1"):
        vectors, meta = baseline_index
        emb = get_embedding_provider()
        q_vec = await emb.encode(tc.question)
        hits = baseline_rag_service.search_baseline(
            tc.question, q_vec, vectors, meta,
            top_k=baseline_top_k, hybrid=(raw_arm == "B1"),
            reranker=reranker if raw_arm == "B1" else None,
        )
        context_lines = baseline_rag_service.build_context_lines(hits)
        retrieved_texts = [h.get("chunk_text", "") for h in hits]
        chunk_ids = [f"{h.get('source')}_{h.get('chunk_index')}" for h in hits]

        gen = None
        async for item in agent._generate_from_context_lines(
            tc.question, history=None, cfg=cfg,
            llm_provider=counting,
            judge_llm_provider=judge_counting or counting,
            kg_id=kg_id, use_svo=True, context_lines=context_lines,
        ):
            if isinstance(item, agent._GenerationResult):
                gen = item
        r = {
            "answer": gen.final_answer if gen else "",
            "error": None,
            "regenerated": gen.regenerated if gen else None,
            "triples": [],
            "facts": [],
            "grounding": [
                {"statement": c.statement, "is_claim": c.is_claim, "supported": c.supported}
                for c in (gen.grounding if gen else [])
            ],
        }
    else:  # F / G / K / K-2b
        mode = {"F": "fact_only", "G": "bfs_only", "K": "both", "K-2b": "both"}.get(raw_arm, "both")
        r = await _drain_chat(ChatRequest(
            question=tc.question, kg_id=kg_id, use_svo=True,
            retrieval_mode=mode, disable_grounding_regen=(raw_arm == "K-2b"),
            scope_doc_ids=scope_uuids,
        ))
        # 報告57任務C Stage 1真實資料發現（2026-09-15）：`r["triples"]`／`r["facts"]`
        # 是JSON往返解碼出來的dict，`natural_text`/`source_doc_id`/`fact_text`/
        # `fact_id`這些鍵永遠存在但值可能是JSON null（例如`_serialize_sources()`
        # 的`fact_id`欄位本來就設計成不外洩、恆為null——見
        # `services/svo_service.py::vector_search_facts()`與其測試
        # `test_rrf_fuse_fact_ids...`的「內部欄位不外洩」契約）。`dict.get(key,
        # default)`只在鍵缺席時套用default，鍵存在但值為None時直接回傳None，
        # 導致`"".join(retrieved_texts)`炸TypeError、`RetrievalStageLineage`
        # pydantic驗證因`List[str]`欄位收到None炸ValidationError——先前批次
        # 剛好沒有問題觸發到足量facts/None欄位，這次三題健康檢查聚合題才第一次
        # 真實暴露。改用`x.get(key) or default`同時擋掉「鍵缺席」與「值為None」
        # 兩種情況。
        retrieved_texts = [(t.get("natural_text") or "") for t in r["triples"]] + [(f.get("fact_text") or "") for f in r["facts"]]
        chunk_ids = [(t.get("source_doc_id") or "") for t in r["triples"]]
        fact_ids = [(f.get("fact_id") or "") for f in r["facts"]]
        context_lines = retrieved_texts

    latency_s = round(time.perf_counter() - t0, 2)
    answer = r["answer"]

    # 階段一血統（2026-09-15依使用者裁示統一改用語意fallback版——見報告57
    # §4.2 Stage 1發現：SVO自然化後的Fact文字跟exact_span原文不逐字相同時
    # （例如少了「，應」連接詞、句號），嚴格逐字比對版本會錯判成「檢索失敗」，
    # 即使語意上答案已正確且最終AtomicScorer已用語意fallback判定命中——兩層
    # 量測基準不一致。改用_async版本，逐字比對失敗才補呼叫judge做語意蘊含
    # 核對，與AtomicScorer.evaluate_async()同一套判準）
    await tracker.record_retrieval_async(
        retrieved_texts, gold_spans, latency_ms=latency_s * 1000,
        chunk_ids=chunk_ids, fact_ids=fact_ids,
        judge_llm_provider=judge_counting or counting, question=tc.question,
        atomic_gold_facts=tc.atomic_gold_facts,
    )
    # 階段二血統（同上，語意fallback版）
    full_context_str = "\n".join(context_lines)
    await tracker.record_context_assembly_async(
        full_context_str, gold_spans, total_tokens=len(full_context_str) // 4,
        judge_llm_provider=judge_counting or counting, question=tc.question,
    )

    # 確定性法律守衛必須在最終答案產生後、AtomicScorer 與 generation lineage
    # 寫入前執行。guard 失敗只阻斷 question-level perfect，不覆寫原始答案，
    # 以便後續區分「coverage 足夠但法律關鍵詞被改寫」與「根本沒有召回證據」。
    guard_result = DeterministicGuardService.verify_draft(
        context_text=full_context_str,
        fact_lines=context_lines,
        question=tc.question,
        draft_answer=answer,
        allowed_articles=[tc.source_article] if tc.source_article else None,
    )

    # 階段三血統
    tracker.record_generation(
        raw_draft=answer,
        final_output=answer,
        grounding_passed=all(c.get("supported", False) for c in r["grounding"] if c.get("is_claim")),
        latency_ms=latency_s * 1000,
        llm_model=_configured_model(settings.llm_provider) or "unknown",
        regenerated=bool(r["regenerated"]),
        deterministic_guard_triggered=not guard_result.is_valid,
        guard_reasons=(
            [guard_result.failure_reason]
            if guard_result.failure_reason
            else []
        ),
    )

    # 執行確定性原子事實評分（語意 NLI fallback 版，報告52/55）：exact_span
    # 逐字比對失敗才補呼叫獨立 judge 做語意蘊含核對，不影響已逐字命中的案例。
    refusal_exp = (tc.scenario_type == "Type-E")
    atomic_eval = await AtomicScorer.evaluate_async(
        answer,
        tc.atomic_gold_facts,
        refusal_expected=refusal_exp,
        judge_llm_provider=judge_counting or counting,
        question=tc.question,
        deterministic_guard_passed=guard_result.is_valid,
        guard_failures=(
            [guard_result.failure_reason]
            if guard_result.failure_reason
            else []
        ),
        trap_claim_spans=tc.trap_claim_spans,
    )
    scope_audit = audit_answer_scope(answer, tc)

    full_lineage = await tracker.build_full_lineage_async(
        gold_spans, judge_llm_provider=judge_counting or counting, question=tc.question,
    )

    return {
        "question_id": tc.id,
        "arm": arm,
        "raw_arm": raw_arm,
        "scenario_type": tc.scenario_type.value,
        "answer": answer,
        "error": r["error"],
        "latency_s": latency_s,
        "llm_calls": counting.calls,
        "generation_llm_calls": counting.calls,
        "judge_llm_calls": judge_counting.calls if judge_counting is not None else 0,
        "generator_provider": settings.llm_provider,
        "generator_model": _configured_model(settings.llm_provider),
        "judge_provider": settings.judge_llm_provider or settings.llm_provider,
        "judge_model": _configured_model(
            settings.judge_llm_provider or settings.llm_provider,
            judge=True,
        ),
        "estimated_tokens": len(full_context_str) // 4 + len(answer) // 4,
        "atomic_score": atomic_eval.model_dump(),
        "scope_audit": scope_audit,
        "lineage": full_lineage.model_dump(),
        "failure_attribution": full_lineage.failure_attribution,
        "deterministic_guard": guard_result.model_dump(),
    }


def _render_pareto_summary(
    out_dir: Path,
    manifest: dict,
    records: list[dict],
    arms: list[str],
    test_cases: list[TestCase],
) -> None:
    """生成包含三階段生命週期成本與原子事實準確率的 Pareto 評估報告"""
    q_map = {tc.id: tc for tc in test_cases}
    by_arm_qid = {}
    for r in records:
        by_arm_qid.setdefault((r["arm"], r["question_id"]), []).append(r)

    summary_lines = [
        "# RQ1 統一評測報告：Pareto 最優邊界與全生命週期成本矩陣",
        "",
        f"> 生成時間：{datetime.now(timezone.utc).isoformat()}",
        f"> 基準圖譜：`{manifest.get('kg_id')}` | 評測題數：{len(test_cases)} 題 | 每題重複：{manifest.get('runs', 3)} 次",
        "",
        "## 1. 核心四大代表方法 Pareto 表現矩陣",
        "",
        "| 方法代號 | 代表架構 | 原子事實正確率 (Acc) | 必要事實召回率 (Rec) | 服務期 p50 延遲 (s) | 建庫膨脹比 | 千次查詢預估 (USD) |",
        "|---|---|---|---|---|---|---|",
    ]

    for arm in arms:
        arm_recs = [r for r in records if r["arm"] == arm]
        if not arm_recs:
            continue
        acc = statistics.mean([r["atomic_score"]["atomic_accuracy"] for r in arm_recs])
        rec = statistics.mean([r["atomic_score"]["atomic_recall"] for r in arm_recs])
        latencies_ms = [r["latency_s"] * 1000 for r in arm_recs]
        tokens = [r.get("estimated_tokens", 500) for r in arm_recs]

        serving_cost = CostAnalyzer.compute_serving_cost(arm, latencies_ms, tokens)
        profile = CostAnalyzer.get_baseline_profile(arm)

        summary_lines.append(
            f"| **{arm}** | {arm_recs[0]['raw_arm']} | {acc*100:.1f}% | {rec*100:.1f}% | "
            f"{serving_cost.latency_p50_ms/1000:.2f}s | {profile.build_cost.storage_multiplier}x | "
            f"${serving_cost.estimated_cost_per_1k_queries_usd:.4f} |"
        )

    summary_lines.extend([
        "",
        "## 2. Context Quality 矩陣（維度I，純檢索品質，不受生成端干擾——報告57 §2）",
        "",
        "| 方法代號 | Context Recall | SNR（信噪比） | Chain Completeness（僅跨文件題） |",
        "|---|---|---|---|",
    ])

    for arm in arms:
        arm_recs = [r for r in records if r["arm"] == arm]
        if not arm_recs:
            continue
        stage1_list = [r["lineage"]["stage1_retrieval"] for r in arm_recs]
        recall_vals = [s["recall_rate"] for s in stage1_list]
        snr_vals = [s["snr"] for s in stage1_list]
        chain_vals = [
            s["chain_completeness"] for s in stage1_list
            if s.get("chain_completeness") is not None
        ]
        recall_avg = statistics.mean(recall_vals) if recall_vals else 0.0
        snr_avg = statistics.mean(snr_vals) if snr_vals else 0.0
        if chain_vals:
            chain_display = f"{statistics.mean(chain_vals)*100:.1f}% (n={len(chain_vals)})"
        else:
            chain_display = "N/A（無跨文件題樣本）"
        summary_lines.append(
            f"| **{arm}** | {recall_avg*100:.1f}% | {snr_avg*100:.1f}% | {chain_display} |"
        )

    summary_lines.extend([
        "",
        "## 3. 場景梯度細分（Type-A ~ Type-E）表現",
        "",
        "| 題號 | 場景分類 | " + " | ".join(arms) + " |",
        "|---|---| " + " | ".join(["---"] * len(arms)) + " |",
    ])

    for tc in test_cases:
        row = [f"**{tc.id}**", f"`{tc.scenario_type.value}`"]
        for arm in arms:
            recs = by_arm_qid.get((arm, tc.id), [])
            if not recs:
                row.append("—")
                continue
            acc = statistics.mean([r["atomic_score"]["atomic_accuracy"] for r in recs])
            perfect = sum(1 for r in recs if r["atomic_score"]["is_perfect"])
            row.append(f"{acc*100:.0f}% ({perfect}/{len(recs)}✓)")
        summary_lines.append("| " + " | ".join(row) + " |")

    summary_lines.extend([
        "",
        "## 4. 典型缺陷全鏈路血統歸因",
        "",
        "| 題號 | 方法 | 錯誤診斷 | 歸因原因 |",
        "|---|---|---|---|",
    ])

    for r in records:
        if not r["atomic_score"]["is_perfect"] and "Success" not in r["failure_attribution"]:
            summary_lines.append(
                f"| {r['question_id']} | {r['arm']} | 瑕疵 | {r['failure_attribution']} |"
            )

    out_file = out_dir / "summary.md"
    out_file.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"✅ Summary report generated at {out_file}")


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _configured_model(provider: str, *, judge: bool = False) -> str | None:
    """回傳 manifest 應記錄的 provider model，不暴露 API key。"""
    if judge and settings.judge_llm_model:
        return settings.judge_llm_model
    model_by_provider = {
        "ollama": settings.ollama_llm_model,
        "openai": settings.openai_llm_model,
        "anthropic": settings.anthropic_model,
        "gemini": settings.gemini_model,
        "grok": settings.grok_model,
    }
    if provider == "local":
        return settings.local_embedding_model
    return model_by_provider.get(provider)


def _configured_embedding_model(provider: str) -> str | None:
    model_by_provider = {
        "local": settings.local_embedding_model,
        "openai": settings.openai_embedding_model,
        "ollama": settings.ollama_embedding_model,
    }
    return model_by_provider.get(provider)


def _build_failure_record(
    tc: TestCase,
    arm: str,
    run_index: int,
    *,
    error_code: str,
    failure_reason: str,
    guard_name: str,
    latency_s: float,
) -> dict:
    """將單筆 harness 例外轉成可統計、且仍具三階段 lineage 的 failure record。"""
    gold_spans = [fact.exact_span for fact in tc.atomic_gold_facts]
    tracker = LineageTracker(tc.id, arm, tc.question)
    tracker.record_retrieval(
        [], gold_spans, latency_ms=latency_s * 1000, atomic_gold_facts=tc.atomic_gold_facts,
    )
    tracker.record_context_assembly("", gold_spans, total_tokens=0)
    tracker.record_generation(
        raw_draft="",
        final_output="",
        grounding_passed=False,
        latency_ms=latency_s * 1000,
    )
    lineage = tracker.build_full_lineage(gold_spans).model_dump()
    atomic = AtomicScorer.evaluate(
        "",
        tc.atomic_gold_facts,
        refusal_expected=(tc.scenario_type == "Type-E"),
        deterministic_guard_passed=False,
        guard_failures=[f"{guard_name}: {failure_reason}"],
    ).model_dump()
    return {
        "question_id": tc.id,
        "arm": arm,
        "raw_arm": ARM_ALIAS_MAP.get(arm, arm),
        "run": run_index,
        "scenario_type": tc.scenario_type.value,
        "answer": "",
        "error": error_code,
        "latency_s": latency_s,
        "llm_calls": None,
        "generation_llm_calls": None,
        "judge_llm_calls": None,
        "estimated_tokens": 0,
        "atomic_score": atomic,
        "scope_audit": {
            "checked_rule_count": len(tc.claim_audit_rules),
            "issue_count": None,
            "issues": [],
            "passed": None,
            "status": "not_evaluated",
        },
        "lineage": lineage,
        "failure_attribution": failure_reason,
        "deterministic_guard": {
            "is_valid": False,
            "guard_name": guard_name,
            "failure_reason": failure_reason,
            "extra_constrained_note": None,
        },
    }


def _build_timeout_record(tc: TestCase, arm: str, run_index: int, timeout_s: float) -> dict:
    """將單筆 timeout 轉成可統計的 failure record。"""
    return _build_failure_record(
        tc,
        arm,
        run_index,
        error_code=f"harness_timeout_after_{timeout_s}s",
        failure_reason=f"Harness Timeout after {timeout_s}s",
        guard_name="HarnessTimeout",
        latency_s=timeout_s,
    )


def _build_exception_record(
    tc: TestCase,
    arm: str,
    run_index: int,
    exc: Exception,
    latency_s: float,
) -> dict:
    detail = f"{type(exc).__name__}: {exc}".strip()
    return _build_failure_record(
        tc,
        arm,
        run_index,
        error_code="harness_exception",
        failure_reason=f"Harness Exception: {detail}",
        guard_name="HarnessException",
        latency_s=latency_s,
    )


async def _run_harness(args, out_dir: Path, test_cases: list[TestCase], manifest: dict) -> None:
    """初始化依賴、執行完整 factorial harness，並以 finally 關閉資料庫。"""
    await connect()
    try:
        init_providers()
        generator = get_llm_provider()
        judge = get_judge_llm_provider(generator)
        generator_provider = settings.llm_provider
        generator_model = _configured_model(generator_provider)
        judge_provider = settings.judge_llm_provider or generator_provider
        judge_model = _configured_model(judge_provider, judge=True)
        same_judge_config = (
            judge_provider == generator_provider
            and judge_model == generator_model
        )
        if (judge is generator or same_judge_config) and not args.allow_shared_judge:
            raise SystemExit(
                "正式評測需要獨立 judge provider；請設定 JUDGE_LLM_PROVIDER，"
                "且 judge model 不得與生成端相同；或僅在 pilot 明確傳入 "
                "--allow-shared-judge。"
            )

        driver = get_driver()
        kg_meta = await KGRepository(driver).get(UUID(args.kg_id))
        domain_pack = kg_meta.domain_pack if kg_meta is not None else None
        cfg = ConfigLoader([FileConfigSource(settings.kg_config_dir)]).load(
            UUID(args.kg_id), domain_pack=domain_pack,
        )
        scope_uuids, sources = _resolve_scope(UUID(args.kg_id), [
            d.strip() for d in args.doc_ids.split(",") if d.strip()
        ])

        raw_arms = {ARM_ALIAS_MAP.get(arm, arm) for arm in args.arms}
        baseline_index = None
        if raw_arms.intersection({"B0", "B1"}):
            baseline_index = _load_scoped_baseline_index(
                UUID(args.kg_id), args.chunk_size, sources,
            )

        generator_counter = _CountingLLM(generator)
        judge_counter = _CountingLLM(judge)
        records: list[dict] = []
        records_path = out_dir / "records.json"
        records_path.write_text("[]", encoding="utf-8")
        for test_case in test_cases:
            for arm in args.arms:
                for run_index in range(1, args.runs + 1):
                    query_started = time.perf_counter()
                    try:
                        record = await asyncio.wait_for(
                            _run_single_query(
                                test_case,
                                arm,
                                UUID(args.kg_id),
                                scope_uuids,
                                cfg,
                                generator_counter,
                                judge_counter,
                                baseline_index,
                                None,
                                args.baseline_top_k,
                            ),
                            timeout=args.query_timeout_s,
                        )
                        record["run"] = run_index
                    except asyncio.TimeoutError:
                        record = _build_timeout_record(
                            test_case, arm, run_index, args.query_timeout_s,
                        )
                    except Exception as exc:
                        record = _build_exception_record(
                            test_case,
                            arm,
                            run_index,
                            exc,
                            round(time.perf_counter() - query_started, 2),
                        )
                    records.append(record)
                    records_path.write_text(
                        json.dumps(records, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

        records_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest["status"] = "completed"
        manifest["records_count"] = len(records)
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _render_pareto_summary(out_dir, manifest, records, args.arms, test_cases)
        print(f"✅ {len(records)} records written to {out_dir / 'records.json'}")
    finally:
        await disconnect()


def main():
    parser = argparse.ArgumentParser(description="RQ1 統一標準化評測 Harness")
    parser.add_argument("--kg-id", default="236903cf-055a-40a8-8923-b9d06601f3b7")
    parser.add_argument("--doc-ids", default="D0080015_警察人員特別休假辦法,F0040034_員工接受召集請假期間薪資費用加成減除辦法,N0030006_勞工請假規則,N0030018_育嬰留職停薪實施辦法,N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法,N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法")
    parser.add_argument("--questions", default=str(DEFAULT_TEST_CASES_PATH))
    parser.add_argument("--arms", default="M1,M2,M3,M4")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--baseline-top-k", type=int, default=5)
    parser.add_argument("--query-timeout-s", type=float, default=180.0)
    parser.add_argument("--complexity", default="all")
    parser.add_argument("--out", default="rq1_eval_results")
    parser.add_argument(
        "--allow-shared-judge",
        action="store_true",
        help="僅供 pilot；允許生成器與 judge 共用 provider，正式評測不應使用。",
    )

    args = parser.parse_args()
    kg_uuid = UUID(args.kg_id)
    doc_id_list = [d.strip() for d in args.doc_ids.split(",") if d.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    args.arms = arms

    if args.runs < 1 or args.baseline_top_k < 1 or args.query_timeout_s <= 0:
        raise SystemExit("--runs、--baseline-top-k 與 --query-timeout-s 必須是正數。")

    loaded_test_cases = _load_questions(args.questions, args.complexity)
    test_cases, excluded = split_eligible_test_cases(loaded_test_cases)
    if not test_cases:
        raise SystemExit("沒有符合正式評測資格的題目；請先完成 gold 核驗。")
    print(
        f"Loaded {len(loaded_test_cases)} test cases; "
        f"eligible={len(test_cases)}, excluded={len(excluded)}."
    )

    dataset_path = (
        Path(args.questions)
        if Path(args.questions).is_file()
        else DEFAULT_TEST_CASES_PATH
    )
    dataset_sha256 = _sha256_file(dataset_path)
    generator_provider = settings.llm_provider
    generator_model = _configured_model(generator_provider)
    judge_provider = settings.judge_llm_provider or generator_provider
    judge_model = _configured_model(judge_provider, judge=True)
    preflight = run_evaluation_preflight(
        test_cases=test_cases,
        arms=arms,
        generator_provider=generator_provider,
        generator_model=generator_model,
        judge_provider=judge_provider,
        judge_model=judge_model,
        doc_ids=doc_id_list,
        dataset_sha256=dataset_sha256,
        query_timeout_s=args.query_timeout_s,
        allow_shared_judge=args.allow_shared_judge,
    )
    if not preflight.passed:
        details = "\n".join(f"- {error}" for error in preflight.errors)
        raise SystemExit(f"Preflight FAILED:\n{details}")
    print("Preflight PASSED — ready for formal evaluation.")
    for warning in preflight.warnings:
        print(f"Preflight WARNING — {warning}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_outputs = [
        name for name in ("manifest.json", "records.json", "summary.md")
        if (out_dir / name).exists()
    ]
    if existing_outputs:
        raise SystemExit(
            f"輸出目錄已有結果檔案 {existing_outputs}；請使用新的 --out，避免覆寫既有實驗。"
        )

    manifest = {
        "kg_id": str(kg_uuid),
        "arms": arms,
        "runs": args.runs,
        "chunk_size": args.chunk_size,
        "doc_ids": doc_id_list,
        "requested_questions_count": len(loaded_test_cases),
        "questions_count": len(test_cases),
        "eligible_question_ids": [tc.id for tc in test_cases],
        "excluded_questions": excluded,
        "formal_evaluation": not args.allow_shared_judge and not (
            (settings.judge_llm_provider or settings.llm_provider) == settings.llm_provider
            and _configured_model(
                settings.judge_llm_provider or settings.llm_provider,
                judge=True,
            ) == _configured_model(settings.llm_provider)
        ),
        "allow_shared_judge": args.allow_shared_judge,
        "generator_provider": generator_provider,
        "generator_model": generator_model,
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": _configured_embedding_model(settings.embedding_provider),
        "query_timeout_s": args.query_timeout_s,
        "dataset_sha256": dataset_sha256,
        "preflight": preflight.as_dict(),
        "status": "initialized",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Harness initialized for arms: {arms}")
    asyncio.run(_run_harness(args, out_dir, test_cases, manifest))


if __name__ == "__main__":
    main()
