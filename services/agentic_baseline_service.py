"""B2 Agentic RAG 強基準的**證據蒐集側**（RQ1 上限對照組，optional）。

對應 `docs/報告/36_B2AgenticRAG強基準設計.md` §3／§7 與論文 §5.4.1。B2 ＝ 在 B1
檢索前端（`services/baseline_rag_service.py`）之上包一層 **single-agent、
prompt-based 的 agentic 多輪迴圈**：

    複雜度路由 → 簡單題退回 B1 單次
              → 複雜題：分解 → 逐子問題〔B1 檢索 → 反思證據是否充分 →
                        不足則依缺口精煉查詢再檢索，≤ max_rounds〕→ 綜合證據

界限（報告 36 §3）：`max_rounds=5`（Fan 2026）、每輪 `top_k=5`、總檢索次數上限、
generator 固定、**無工具（只有檢索）**、**無 RL**、**單 agent**。

## 依賴注入 = 不碰 LLM／索引

`gather_evidence_agentic()` 吃兩個注入函式：
- `retrieve(query) -> list[hit]`：呼叫端用 B1 組態包 `baseline_rag_service.search_baseline`。
- `reflect(subquestion, evidence_texts) -> ReflectVerdict`：呼叫端包一次 LLM 呼叫，
  輸入＝子問題＋當前證據，輸出＝`{sufficient: bool, missing: str}`（報告 36 §7）。

本模組因此**不 import LLM provider、不 import Neo4j**，可用假函式完整單元測試。

## 生成端

**不做生成**。回傳綜合後的證據 `context_lines` ＋ trace（輪數／LLM 呼叫數／
context 長度，供 §5.5 的線上效率與穩定性欄）。最終生成走「與 B0/B1/Full System
逐位元相同的共用 post-retrieval pipeline」（P0b 第 2 項，尚未完成）。

## Confounder 誠實聲明（報告 36 §4）

Full System 的 RQ3 自我精煉迴圈尚未實作 → B2 的多輪檢索**比現行 Full System
更 agentic**。RQ1 提問因此精確化為 Fan (2026) 框架：即使 Full System 沒有 agent
迴圈，顯式 KG-BFS 是否仍在可追溯性／成本／穩定性／複雜多跳上勝過完整 agentic
chunk-RAG。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.baseline_rag_service import build_context_lines

# 與 routers/agent.py::_MAX_SUBQUESTIONS／_split_into_subquestions 對齊（報告 28）；
# services 不反向 import routers，故在此重寫一份。
_MAX_SUBQUESTIONS = 6

# 複雜度路由的規則式判準（報告 36 §7 逐字：「問號數 ≥ 2、或含『且/或/以及/並/
# 分別』等連接詞、或抽出實體數 ≥ 3」；Adaptive-RAG〔Jeong et al. 2024〕式訓練
# 分類器留作後續）。
_CONJUNCTIONS = ("且", "或", "以及", "並", "分別")
_MAX_ROUNDS_DEFAULT = 5
_PER_ROUND_TOP_K_DEFAULT = 5
_RETRIEVAL_BUDGET_DEFAULT = 8


@dataclass(frozen=True)
class ReflectVerdict:
    """`reflect()` 的回傳：當前證據是否足以回答該子問題、若不足缺什麼。"""
    sufficient: bool
    missing: str = ""


@dataclass
class AgenticResult:
    context_lines: list[str]
    complexity: str                       # "simple" | "complex"
    sub_questions: list[str]
    evidence: list[dict]                  # 去重後的 hit（{source, chunk_index, chunk_text, ...}）
    retrieval_calls: int = 0
    reflect_calls: int = 0
    rounds_per_subquestion: list[int] = field(default_factory=list)

    @property
    def context_char_len(self) -> int:
        return sum(len(line) for line in self.context_lines)


# ── 複雜度路由（報告 36 §7）───────────────────────────────────────

def route_complexity(question: str, *, entity_count: int | None = None) -> str:
    """規則式複雜度分類：問號 ≥ 2、或含並列連接詞、或抽出實體數 ≥ 3 → "complex"。
    否則 "simple"（退回 B1 單次，成本對照才公平）。"""
    if len(re.findall(r"[？?]", question)) >= 2:
        return "complex"
    if any(conj in question for conj in _CONJUNCTIONS):
        return "complex"
    if entity_count is not None and entity_count >= 3:
        return "complex"
    return "simple"


# ── 規則式分解（鏡像 routers/agent.py::_split_into_subquestions）────

def split_into_subquestions(question: str) -> list[str]:
    """按句末問號切分複合問題；< 2 個非空子句時原樣回傳 `[question]`。"""
    parts = re.split(r"([？?])", question)
    segments: list[str] = []
    for i in range(0, len(parts) - 1, 2):
        text = parts[i].strip()
        if text:
            segments.append(text + parts[i + 1])
    if len(parts) % 2 == 1:
        trailing = parts[-1].strip()
        if trailing:
            segments.append(trailing)
    if len(segments) < 2:
        return [question]
    return segments[:_MAX_SUBQUESTIONS]


# ── 證據去重 ────────────────────────────────────────────────────

def _dedup_key(hit: dict) -> tuple:
    return (hit.get("source"), hit.get("chunk_index"))


def _merge_evidence(pool: list[dict], seen: set, new_hits: list[dict]) -> None:
    for hit in new_hits:
        key = _dedup_key(hit)
        if key in seen:
            continue
        seen.add(key)
        pool.append(hit)


# ── 主入口 ─────────────────────────────────────────────────────

def gather_evidence_agentic(
    question: str,
    retrieve,
    reflect,
    *,
    entity_count: int | None = None,
    max_rounds: int = _MAX_ROUNDS_DEFAULT,
    per_round_top_k: int = _PER_ROUND_TOP_K_DEFAULT,
    retrieval_budget: int = _RETRIEVAL_BUDGET_DEFAULT,
) -> AgenticResult:
    """B2 證據蒐集。

    參數
    ----
    retrieve : `(query: str, *, top_k: int) -> list[dict]`；呼叫端用 B1 組態包
               `baseline_rag_service.search_baseline`。
    reflect  : `(subquestion: str, evidence_texts: list[str]) -> ReflectVerdict`；
               呼叫端包一次 LLM 呼叫。
    entity_count : 問句抽出的實體數（供 `route_complexity`）；None 時該判準略過。
    max_rounds : 每個子問題的檢索輪數上限（Fan 2026＝5）。
    retrieval_budget : 整題（跨所有子問題）的總檢索次數上限。

    回傳 `AgenticResult`：綜合證據 `context_lines` ＋ trace。
    """
    complexity = route_complexity(question, entity_count=entity_count)
    pool: list[dict] = []
    seen: set = set()
    retrieval_calls = 0
    reflect_calls = 0

    # 簡單題 → B1 單次，不進 agent 迴圈
    if complexity == "simple":
        hits = retrieve(question, top_k=per_round_top_k)
        retrieval_calls += 1
        _merge_evidence(pool, seen, hits)
        return AgenticResult(
            context_lines=build_context_lines(pool),
            complexity=complexity,
            sub_questions=[question],
            evidence=pool,
            retrieval_calls=retrieval_calls,
            reflect_calls=reflect_calls,
            rounds_per_subquestion=[1],
        )

    # 複雜題 → 分解 → 逐子問題多輪
    sub_questions = split_into_subquestions(question)
    rounds_per_sq: list[int] = []
    for sub_q in sub_questions:
        query = sub_q
        rounds = 0
        while rounds < max_rounds and retrieval_calls < retrieval_budget:
            hits = retrieve(query, top_k=per_round_top_k)
            retrieval_calls += 1
            rounds += 1
            _merge_evidence(pool, seen, hits)

            verdict = reflect(sub_q, [h["chunk_text"] for h in pool])
            reflect_calls += 1
            if verdict.sufficient:
                break
            # FLARE 觸發：依缺口精煉下一輪查詢
            missing = (verdict.missing or "").strip()
            query = f"{sub_q} {missing}".strip() if missing else sub_q
        rounds_per_sq.append(rounds)

    return AgenticResult(
        context_lines=build_context_lines(pool),
        complexity=complexity,
        sub_questions=sub_questions,
        evidence=pool,
        retrieval_calls=retrieval_calls,
        reflect_calls=reflect_calls,
        rounds_per_subquestion=rounds_per_sq,
    )
