"""`KGConfig` 與其分區子模型 —— 報告33 §3.9.1 的「約二十個未校準門檻常數」收編。

所有子模型 `frozen=True`：一旦建構，任一層（含巢狀）寫入都拋
`pydantic_core.ValidationError`——支撐「單一行程服務多知識圖譜時無共享可變
狀態的競態」（論文 04 §4.10 驗收標準之一）。

**每個 `Field` 的預設值 = 重構前對應模組常數的現值**，來源標於註解。golden test
（`tests/core/test_kg_config.py`）逐欄位比對 live 常數，任何漂移都會 fail。

第 1 步只收 scalar 常數。domain pack 層的字串欄位（`system_context`、
`svo_fewshots`、`guard_profile` token 清單）於第 3–4 步併入，屆時新增 `domain`
分區。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class RoutingConfig(BaseModel):
    """ConceptNode 路由層與暫存區分類門檻（`core/constants.py`）。"""

    model_config = _FROZEN

    # core/constants.py::KG_ROUTE_THRESHOLD
    kg_route_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    # core/constants.py::CLASSIFY_AUTO_THRESHOLD
    classify_auto_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    # core/constants.py::CLASSIFY_MIN_THRESHOLD
    classify_min_threshold: float = Field(default=0.05, ge=0.0, le=1.0)


class BfsConfig(BaseModel):
    """查詢端 BFS 遍歷與種子（`routers/agent.py`、`services/svo_service.py`）。

    報告27 §6.2 待辦2 / 報告32 §9 的 θ 家族——第 2 步優先接這一區。
    """

    model_config = _FROZEN

    # routers/agent.py::_SEED_ENTITY_LIMIT
    seed_entity_limit: int = Field(default=8, ge=1, le=64)
    # routers/agent.py::_SEED_MAX_DEGREE（2026-09-05 §6.2 單題調校 200→100）
    seed_max_degree: int = Field(default=100, ge=1)
    # routers/agent.py::_BFS_PER_SEED_LIMIT（2026-09-05 §6.2 單題調校 60→30）
    per_seed_limit: int = Field(default=30, ge=1)
    # routers/agent.py::_DOC_SCOPE_TOP_N_FACTS
    doc_scope_top_n_facts: int = Field(default=5, ge=1)
    # services/svo_service.py::_BFS_EXPAND_WHEN_BELOW
    expand_when_below: int = Field(default=8, ge=0)
    # services/svo_service.py::_BFS_PRIZE_TOP_K（報告32 §9 L2，prototype 預設）
    prize_top_k: int = Field(default=10, ge=1)


class FactListConfig(BaseModel):
    """生成端事實清單組裝、排序、融合（`routers/agent.py`）。"""

    model_config = _FROZEN

    # routers/agent.py::_FACT_LINE_TRUNCATE_K
    truncate_k: int = Field(default=18, ge=1)
    # routers/agent.py::_FACT_LINE_REORDER_THRESHOLD_K
    reorder_threshold_k: int = Field(default=35, ge=1)
    # routers/agent.py::_BFS_KEEP_MAX
    bfs_keep_max: int = Field(default=18, ge=1)
    # routers/agent.py::_MIN_BFS_SLOTS
    min_bfs_slots: int = Field(default=4, ge=0)
    # routers/agent.py::_RRF_K（Cormack et al. 2009 文獻值；非未校準常數，收此供覆蓋）
    rrf_k: int = Field(default=60, ge=1)


class DecomposeConfig(BaseModel):
    """複合問題分解與分段清單 completeness guard（`routers/agent.py`）。"""

    model_config = _FROZEN

    # routers/agent.py::_MAX_SUBQUESTIONS
    max_subquestions: int = Field(default=6, ge=1, le=32)
    # routers/agent.py::_TIER_MIN_MEMBERS
    tier_min_members: int = Field(default=3, ge=2)


class DedupConfig(BaseModel):
    """實體模糊合併門檻（`core/constants.py`；`resolve_entity_name()` 三段式）。"""

    model_config = _FROZEN

    # core/constants.py::ENTITY_DEDUP_EDIT_RATIO_THRESHOLD
    edit_ratio_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    # core/constants.py::ENTITY_DEDUP_COSINE_THRESHOLD
    cosine_threshold: float = Field(default=0.88, ge=0.0, le=1.0)
    # core/constants.py::ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD
    escalate_low_threshold: float = Field(default=0.75, ge=0.0, le=1.0)


class RelTypeConfig(BaseModel):
    """關係型別調解門檻（`core/constants.py`；SIM/COMPARE/ESCALATE3、查詢時連結）。"""

    model_config = _FROZEN

    # core/constants.py::COMPARE_COSINE_THRESHOLD
    compare_cosine_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    # core/constants.py::QSIM_ASSIGN_THRESHOLD
    qsim_assign_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    # core/constants.py::QSIM_ESCALATE_LOW_THRESHOLD
    qsim_escalate_low_threshold: float = Field(default=0.60, ge=0.0, le=1.0)


class ExtractionConfig(BaseModel):
    """抽取完整性自檢門檻（報告19）。"""

    model_config = _FROZEN

    # services/svo_service.py::UNCOVERED_SENTENCE_THRESHOLD
    uncovered_sentence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class KGConfig(BaseModel):
    """一個知識圖譜的完整可調整項（第 1 步：scalar 分區）。

    `KGConfig()` = shipped defaults 層，逐欄位等於重構前的模組常數。經
    `ConfigLoader` 疊上 domain pack / per-KG profile / per-request 後仍是同一型別。
    """

    model_config = _FROZEN

    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    bfs: BfsConfig = Field(default_factory=BfsConfig)
    factlist: FactListConfig = Field(default_factory=FactListConfig)
    decompose: DecomposeConfig = Field(default_factory=DecomposeConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    reltype: RelTypeConfig = Field(default_factory=RelTypeConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
