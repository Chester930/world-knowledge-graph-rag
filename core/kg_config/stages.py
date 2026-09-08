"""管線階段登記表 —— 報告33 §4.4「逐階段評分閘控客製化生命週期」的骨架。

**這是宣告式資料,不執行任何東西。** 用途:

1. 把「`KGConfig` 分區 ↔ 評估指標 ↔ gate ↔ 跑它的 harness」的對映集中一處。
2. 收斂報告19/20/25/27/32 散落的診斷成 stage-keyed 定義。
3. 給 `run_theta_sweep.py` / `run_refusal_canary.py` 引用（`STAGE_REGISTRY[...].params`
   取代硬編碼），並餵 §4.4 的生命週期（baseline → 逐階段比 gate → 只客製失敗者）。

**目前狀態**：登記表本身完整;`harness` 為 `MANUAL` 的階段（dedup、reltype、
routing）就是「把報告手動診斷收斂成自動 eval suite」的待辦標的。`blocked_by`
標 `DRAIN_DONE` 的階段要等 KG #4 全量抽完 + Neo4j 在線才跑得起來。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from core.kg_config.model import KGConfig


class Blocker(str, Enum):
    NONE = "none"
    DRAIN_DONE = "drain-done"          # 需 KG #4 全量抽完 + Neo4j 在線
    L2_WIRED = "l2-chat-wiring"        # 需先把 L2 接進 chat()（報告27 §7.2）
    EXTRACTION_SIDE = "extraction-side"  # 動到抽取碼,drain 期間不宜


class Harness(str, Enum):
    THETA_SWEEP = "run_theta_sweep.py"
    REFUSAL_CANARY = "run_refusal_canary.py"
    SELF_CHECK_19_20 = "報告19/20 抽取完整性/數值忠實自檢"
    THESIS_5_3_5 = "論文 §5.3.5 分類門檻校準實驗"
    MANUAL = "manual（尚無自動 harness,靠報告手動診斷）"


Direction = Literal["lower_is_better", "higher_is_better"]


@dataclass(frozen=True)
class Metric:
    name: str
    direction: Direction
    unit: str
    source: str  # 哪份報告/harness 產出這個指標


@dataclass(frozen=True)
class Gate:
    metric: str                       # 對應同 stage 的某個 Metric.name
    comparator: Literal["<=", ">=", "=="]
    threshold: float | str            # 數值,或 "baseline"（相對基準）,或 "3/3" 等
    note: str = ""


@dataclass(frozen=True)
class Stage:
    id: str
    description: str
    config_section: str               # KGConfig 的分區屬性名
    params: tuple[str, ...]           # 該分區裡可調的欄位
    capability_flags: tuple[str, ...] # 可切換的分支（非純量）
    metrics: tuple[Metric, ...]
    gates: tuple[Gate, ...]           # 空 = gate 尚未定義（待第五章）
    harness: Harness
    blocked_by: Blocker = Blocker.NONE


# ── 登記表 ────────────────────────────────────────────────────────────────

_LAT = Metric("latency", "lower_is_better", "s", "報告27 §6.1")
_TRIP = Metric("bfs_triple_count", "lower_is_better", "count", "報告27 §6.1/§6.2")
_HIT = Metric("answer_hit", "higher_is_better", "命中率(×3)", "報告25/26 題組")

STAGE_REGISTRY: dict[str, Stage] = {
    "routing.kg_select": Stage(
        id="routing.kg_select",
        description="ConceptNode 路由層召回門檻（RQ2；目前 chat() 尚未接正式路由）",
        config_section="routing",
        params=("kg_route_threshold",),
        capability_flags=(),
        metrics=(Metric("route_precision", "higher_is_better", "ratio", "RQ2 消融（未跑）"),),
        gates=(),
        harness=Harness.MANUAL,
        blocked_by=Blocker.DRAIN_DONE,
    ),
    "routing.classify": Stage(
        id="routing.classify",
        description="暫存區文件分類 AUTO/SUGGEST/POOL 門檻",
        config_section="routing",
        params=("classify_auto_threshold", "classify_min_threshold"),
        capability_flags=(),
        metrics=(
            Metric("classify_precision", "higher_is_better", "ratio", "論文 §5.3.5"),
            Metric("classify_recall", "higher_is_better", "ratio", "論文 §5.3.5"),
        ),
        gates=(),  # 待論文 §5.3.5 校準實驗
        harness=Harness.THESIS_5_3_5,
    ),
    "retrieval.bfs": Stage(
        id="retrieval.bfs",
        description="查詢端 BFS 遍歷 θ 家族（報告27 §6.2 / 報告32 §9 的主要調校目標）",
        config_section="bfs",
        params=(
            "seed_entity_limit", "seed_max_degree", "per_seed_limit",
            "doc_scope_top_n_facts", "expand_when_below",
        ),
        capability_flags=(),
        metrics=(_LAT, _TRIP, _HIT),
        gates=(
            Gate("latency", "<=", 90.0, "報告27 §6.2：Q7 目標 <90s"),
            Gate("bfs_triple_count", "<=", 30.0, "報告27 §6.2：Q6 目標 <30"),
            Gate("answer_hit", ">=", "baseline", "調 θ 不得使既有正確性退步"),
        ),
        harness=Harness.THETA_SWEEP,
        blocked_by=Blocker.DRAIN_DONE,
    ),
    "retrieval.prize_pruning": Stage(
        id="retrieval.prize_pruning",
        description="L2 向量引導 prize 剪枝（報告27 §7.2 prototype，chat() 未接線）",
        config_section="bfs",
        params=("prize_top_k",),
        capability_flags=("l2_enabled",),  # = 在 chat() 傳三參數
        metrics=(_LAT, _TRIP, _HIT),
        gates=(Gate("answer_hit", ">=", "baseline", "L2 不得使正確性退步"),),
        harness=Harness.THETA_SWEEP,   # run_theta_sweep.py --with-l2
        blocked_by=Blocker.L2_WIRED,
    ),
    "retrieval.factlist": Stage(
        id="retrieval.factlist",
        description="生成端事實清單組裝、截斷、RRF 融合的 K 值",
        config_section="factlist",
        params=("truncate_k", "reorder_threshold_k", "bfs_keep_max", "min_bfs_slots", "rrf_k"),
        capability_flags=(),
        metrics=(_HIT, Metric("answer_muddle", "lower_is_better", "定性", "報告25 §6")),
        gates=(),  # 報告25 §6：K 值敏感度測試待第五章
        harness=Harness.THETA_SWEEP,
        blocked_by=Blocker.DRAIN_DONE,
    ),
    "generation.selective_refusal": Stage(
        id="generation.selective_refusal",
        description="誠實拒答校準（報告32 §9 C；RefusalBench FRR/MRR）",
        config_section="domain",
        params=("system_context",),  # 生成 prompt 前綴影響拒答傾向
        capability_flags=("guard_profile",),
        metrics=(
            Metric("FRR", "lower_is_better", "ratio", "報告32 §9 C / RefusalBench"),
            Metric("MRR", "lower_is_better", "ratio", "報告32 §9 C / RefusalBench"),
            Metric("DetAcc", "higher_is_better", "ratio", "報告32 §9 C"),
        ),
        gates=(
            Gate("MRR", "<=", "baseline", "報告32 §9 C 閘門：不得高於 ed32291 基準"),
            Gate("DetAcc", ">=", 0.0, "報26 Q7 維持 3/3 REFUSE、P5 維持 3/3 ANSWER（硬錨）"),
        ),
        harness=Harness.REFUSAL_CANARY,
        blocked_by=Blocker.DRAIN_DONE,
    ),
    "generation.decompose": Stage(
        id="generation.decompose",
        description="複合問題分解 + 分段清單 completeness guard（報告27 C#2 / 報告32 §9 G3）",
        config_section="decompose",
        params=("max_subquestions", "tier_min_members"),
        capability_flags=(),
        metrics=(_HIT, Metric("tier_completeness", "higher_is_better", "分段答全率", "報告32 §9 G3")),
        gates=(),
        harness=Harness.MANUAL,
        blocked_by=Blocker.DRAIN_DONE,
    ),
    "dedup.entity": Stage(
        id="dedup.entity",
        description="實體模糊合併三段門檻（報告25 發現C/E1、報告32 §9 DEDUP 診斷）",
        config_section="dedup",
        params=("edit_ratio_threshold", "cosine_threshold", "escalate_low_threshold"),
        capability_flags=("guard_profile",),
        metrics=(
            Metric("mis_merge_count", "lower_is_better", "組", "報告32 §9 Test A（E1 誤併數）"),
            Metric("node_redundancy", "lower_is_better", "alias>1 節點數", "報告32 §9.5"),
        ),
        gates=(),  # 靠報告手動診斷,尚無 gate
        harness=Harness.MANUAL,
        blocked_by=Blocker.EXTRACTION_SIDE,
    ),
    "reltype.reconcile": Stage(
        id="reltype.reconcile",
        description="關係型別調解門檻（SIM/COMPARE/ESCALATE3 抽取側 + QSIM 查詢側）",
        config_section="reltype",
        params=("compare_cosine_threshold", "qsim_assign_threshold", "qsim_escalate_low_threshold"),
        capability_flags=(),
        metrics=(Metric("reltype_misclass", "lower_is_better", "ratio", "報告手動診斷"),),
        gates=(),
        harness=Harness.MANUAL,
        blocked_by=Blocker.EXTRACTION_SIDE,  # COMPARE 抽取也用；QSIM 半可先做（8c-4）
    ),
    "extraction.completeness": Stage(
        id="extraction.completeness",
        description="抽取完整性自檢門檻（報告19/20）",
        config_section="extraction",
        params=("uncovered_sentence_threshold",),
        capability_flags=(),
        metrics=(
            Metric("memory_integrity", "higher_is_better", "ratio", "報告19（ProMem τmatch）"),
            Metric("quantity_fidelity", "higher_is_better", "ratio", "報告20"),
        ),
        gates=(),
        harness=Harness.SELF_CHECK_19_20,
        blocked_by=Blocker.EXTRACTION_SIDE,
    ),
}


# ── 一致性檢查（給 tests 用）+ 便利查詢 ───────────────────────────────────

def _kgconfig_sections() -> set[str]:
    return set(KGConfig().model_dump().keys())


def sections_covered() -> set[str]:
    return {s.config_section for s in STAGE_REGISTRY.values()}


def stages_for_section(section: str) -> list[Stage]:
    return [s for s in STAGE_REGISTRY.values() if s.config_section == section]


def unblocked_stages() -> list[Stage]:
    """`blocked_by == NONE` 的階段——現在就能跑 eval 的。"""
    return [s for s in STAGE_REGISTRY.values() if s.blocked_by is Blocker.NONE]


def stages_without_harness() -> list[Stage]:
    """`harness == MANUAL` 的階段——「收斂成自動 eval suite」的待辦標的。"""
    return [s for s in STAGE_REGISTRY.values() if s.harness is Harness.MANUAL]
