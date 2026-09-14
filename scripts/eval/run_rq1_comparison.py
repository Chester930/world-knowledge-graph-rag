"""RQ1 統一評測 Harness（SDD-2.1 交付物）。

支援：
- 四大核心代表方法（M1: Naive Chunk B0、M2: Hybrid Text B1、M3: Fact Vector F、M4: Full KG K）及消融組（D, G, K-2b）。
- 自動調用 AtomicScorer 執行原子法規真值比對（exact_span 逐字核驗）。
- 全鏈路 LineageTracker 記錄（因果隔離檢索、組裝與生成三階段）。
- 三階段 CostAnalyzer 生命週期成本報告與 Pareto 矩陣產出。

⚠️ **入庫時審查發現（2026-09-14）**：`main()` 目前只載入題庫、寫出 `manifest.json`、
印一行「Harness initialized」訊息就結束——`_run_single_query()`／`_render_pareto_summary()`
等實際跑測與產出報告的函式都已經寫好，但**從未在 `main()` 裡被呼叫**。這代表直接執行
本腳本**不會**真的跑任何比較、也不會產出報告43(黃金版Benchmark，現編號 44)驗收標準
要求的結構化結果 JSON——`main()` 需要補上「對 `test_cases × arms × runs` 迴圈呼叫
`_run_single_query()`，收集結果後呼叫 `_render_pareto_summary()`」這段串接邏輯才能真正
跑起來。這是下一步待辦，本次入庫只做了誠實標註，未替使用者決定串接的細節
（例如要不要先跑小樣本、baseline 索引/reranker 的載入時機），留給使用者或下一輪任務決定。
"""
from __future__ import annotations

import argparse
import asyncio
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
from services.cost_analyzer import CostAnalyzer
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
    baseline_index,
    reranker,
    baseline_top_k: int,
) -> dict:
    counting.reset()
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
        retrieved_texts = [h.get("text", "") for h in hits]
        chunk_ids = [f"{h.get('source')}_{h.get('chunk_index')}" for h in hits]

        gen = None
        async for item in agent._generate_from_context_lines(
            tc.question, history=None, cfg=cfg,
            llm_provider=counting, judge_llm_provider=counting,
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
        retrieved_texts = [t.get("natural_text", "") for t in r["triples"]] + [f.get("fact_text", "") for f in r["facts"]]
        chunk_ids = [t.get("source_doc_id", "") for t in r["triples"]]
        fact_ids = [f.get("fact_id", "") for f in r["facts"]]
        context_lines = retrieved_texts

    latency_s = round(time.perf_counter() - t0, 2)
    answer = r["answer"]

    # 階段一血統
    tracker.record_retrieval(retrieved_texts, gold_spans, latency_ms=latency_s * 1000, chunk_ids=chunk_ids, fact_ids=fact_ids)
    # 階段二血統
    full_context_str = "\n".join(context_lines)
    tracker.record_context_assembly(full_context_str, gold_spans, total_tokens=len(full_context_str) // 4)
    # 階段三血統
    tracker.record_generation(
        raw_draft=answer,
        final_output=answer,
        grounding_passed=all(c.get("supported", False) for c in r["grounding"] if c.get("is_claim")),
        latency_ms=latency_s * 1000,
        regenerated=bool(r["regenerated"]),
    )

    # 執行確定性原子事實評分
    refusal_exp = (tc.scenario_type == "Type-E")
    atomic_eval = AtomicScorer.evaluate(answer, tc.atomic_gold_facts, refusal_expected=refusal_exp)

    full_lineage = tracker.build_full_lineage(gold_spans)

    return {
        "question_id": tc.id,
        "arm": arm,
        "raw_arm": raw_arm,
        "scenario_type": tc.scenario_type.value,
        "answer": answer,
        "error": r["error"],
        "latency_s": latency_s,
        "llm_calls": counting.calls,
        "estimated_tokens": len(full_context_str) // 4 + len(answer) // 4,
        "atomic_score": atomic_eval.model_dump(),
        "lineage": full_lineage.model_dump(),
        "failure_attribution": full_lineage.failure_attribution,
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
        "## 2. 場景梯度細分（Type-A ~ Type-E）表現",
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
        "## 3. 典型缺陷全鏈路血統歸因",
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


def main():
    parser = argparse.ArgumentParser(description="RQ1 統一標準化評測 Harness")
    parser.add_argument("--kg-id", default="236903cf-055a-40a8-8923-b9d06601f3b7")
    parser.add_argument("--doc-ids", default="D0080015_警察人員特別休假辦法,F0040034_員工接受召集請假期間薪資費用加成減除辦法,N0030006_勞工請假規則,N0030018_育嬰留職停薪實施辦法,N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法,N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法")
    parser.add_argument("--questions", default=str(DEFAULT_TEST_CASES_PATH))
    parser.add_argument("--arms", default="M1,M2,M3,M4")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--complexity", default="all")
    parser.add_argument("--out", default="rq1_eval_results")

    args = parser.parse_args()
    kg_uuid = UUID(args.kg_id)
    doc_id_list = [d.strip() for d in args.doc_ids.split(",") if d.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    test_cases = _load_questions(args.questions, args.complexity)
    print(f"Loaded {len(test_cases)} test cases.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "kg_id": str(kg_uuid),
        "arms": arms,
        "runs": args.runs,
        "chunk_size": args.chunk_size,
        "doc_ids": doc_id_list,
        "questions_count": len(test_cases),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Harness initialized for arms: {arms}")
    print(
        "⚠️ main() 尚未串接 _run_single_query()/_render_pareto_summary()——"
        "目前只寫出 manifest.json，沒有實際執行任何比較或產出結果 JSON。"
        "見本檔案頂部 docstring 的入庫審查註記。"
    )


if __name__ == "__main__":
    main()
