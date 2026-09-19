"""評測題庫與全鏈路血統追蹤的標準資料模型（SDD-1.1 / SDD-1.3 交付物）。

對應論文：
- `docs/論文/05_附錄A_測試題庫.md` (§A.1, §A.3, §A.5)
- `docs/論文/05_實驗設計與評估.md` (§5.2, §5.5)
- `docs/報告/45_多階段SDD改善任務書.md` (SDD-1.1, SDD-1.2, SDD-1.3)
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field


class ScenarioType(str, Enum):
    """5 類問題場景梯度"""
    TYPE_A = "Type-A"  # 單文局部條文
    TYPE_B = "Type-B"  # 數值密集與條件分支
    TYPE_C = "Type-C"  # 跨法規多跳關聯
    TYPE_D = "Type-D"  # 全域反向聚合與統計
    TYPE_E = "Type-E"  # 惡意干擾／未收錄法規拒答


class VerificationStatus(str, Enum):
    """法規原文真值人工核驗狀態"""
    VERIFIED = "verified"      # 已逐字對齊原始法規 exact_span
    UNVERIFIED = "unverified"  # 尚未逐字對齊（排除於正式評分）
    DISPUTED = "disputed"      # 條文詮釋具爭議或存在版本衝突


class AtomicGoldFact(BaseModel):
    """原子黃金事實：100% 錨定中華民國原始法規 exact_span"""
    exact_span: str = Field(description="必須完全存在於法規原文中的字串")
    source_law: str = Field(description="所屬法規名稱，如 N0050030 災區受災勞工保險費補助辦法")
    source_article: str = Field(description="條號或款目，如 §3 或 第3條")
    is_essential: bool = Field(default=True, description="是否為關鍵必要約束（缺之即判定錯誤）")
    note: Optional[str] = Field(default=None, description="備註說明（如推論依據）")


class ClaimAuditRule(BaseModel):
    """題目範圍與條件前提的 deterministic 答案審查規則。

    這些規則只供離線評測使用，不會改變正式 chat 的生成或接地流程。
    ``trigger_patterns`` 是答案文字中要掃描的字串；條件規則若缺少
    ``required_condition_patterns`` 任一條件，就會產生風險事件。
    """

    id: str = Field(description="規則唯一識別碼")
    kind: Literal["out_of_scope", "conditional", "role_mismatch"] = Field(
        description="規則類型：範圍外、條件缺漏或角色／門檻錯置"
    )
    trigger_patterns: List[str] = Field(
        default_factory=list, description="觸發規則的答案文字片段"
    )
    trigger_mode: Literal["all", "any"] = Field(
        default="all", description="trigger_patterns 須全部或任一命中"
    )
    required_condition_patterns: List[str] = Field(
        default_factory=list, description="conditional 規則要求答案明示的條件片段"
    )
    description: str = Field(default="", description="人工核對規則說明")


class TestCase(BaseModel):
    """標準化評測題目"""
    id: str = Field(description="題目唯一識別碼，如 26-Q5")
    question: str = Field(description="測試提問完整文字")
    pcode: Optional[str] = Field(default=None, description="主要關聯之法規 PCode")
    source_article: str = Field(description="法規條號標記")
    gold_answer: str = Field(description="黃金版參考完整回答")
    scenario_type: ScenarioType = Field(default=ScenarioType.TYPE_A, description="場景梯度類別")
    atomic_gold_facts: List[AtomicGoldFact] = Field(default_factory=list, description="原子黃金事實集合")
    verification_status: VerificationStatus = Field(default=VerificationStatus.UNVERIFIED, description="真值核驗狀態")
    complexity_label: Optional[str] = Field(default=None, description="原始複雜度標籤")
    complexity_bucket: str = Field(default="single", description="single 或 multi")
    wording_status: str = Field(default="verbatim", description="verbatim 或 gist")
    source_report: Optional[str] = Field(default=None, description="題組來源報告")
    dup_map: List[str] = Field(default_factory=list, description="重複或鏡像題目列表")
    pilot: bool = Field(default=False, description="是否為前導/核心基準題")
    mechanism_tags: List[str] = Field(
        default_factory=list,
        description=(
            "檢索機制挑戰標籤（複選，正交於 scenario_type，報告57 §3.2）："
            "single_fact/multi_fact_assembly/cross_doc_multihop/alias_mapping/"
            "coreference_resolution/global_aggregation/interval_lookup/"
            "segmented_enumeration/distractor_adjacent/canary_refusal"
        ),
    )
    answer_scope: Optional[str] = Field(
        default=None, description="答案應涵蓋的範圍與適用條件（離線審查用）"
    )
    required_claims: List[str] = Field(
        default_factory=list,
        description="人工定義的必要主張標籤；原子逐字真值仍以 atomic_gold_facts 為準",
    )
    claim_audit_rules: List[ClaimAuditRule] = Field(
        default_factory=list,
        description="題目範圍外主張與條件／角色錯置的 deterministic 審查規則",
    )
    trap_claim_spans: List[str] = Field(
        default_factory=list,
        description=(
            "僅 Type-E（canary_refusal）題目使用，選填。答案文字裡出現任一則列出的"
            "字串，視為模型確信斷言了這題設計要抓的錯誤結論（陷阱），即使文字別處"
            "也出現拒答措辭，仍判定拒答失敗（報告57 §4.3——AtomicScorer.evaluate()"
            "原本只要答案全文任一處出現拒答關鍵字就判定整題拒答成功，未檢查是否"
            "同時斷言了陷阱結論，會被『答案結尾夾帶一句無關的拒答用語』騙過）。"
            "刻意維持純字串比對（不用LLM judge）——RefusalBench（Muhamed et al. "
            "2025）實測Qwen家族選擇性拒答判斷準確率全尺寸<17%，跟本專案"
            "services/interval_lookup_service.py既有的G2方案E（查表判斷移出LLM "
            "改用確定性Python檢查）原則一致。**只在陷阱結論能表達成固定字串時"
            "才填**——『開放式捏造具體數字』型陷阱（如捏造罰鍰金額、天數）的"
            "陷阱關鍵詞在正確拒答時也會自然出現（用來否定它），加字串比對反而會"
            "製造假陰性，這類題目留空。"
        ),
    )


class EvaluationDataset(BaseModel):
    """標準題庫集合容器"""
    meta: dict[str, Any] = Field(default_factory=dict)
    questions: List[TestCase] = Field(default_factory=list)


# ── 血統追蹤器資料結構（Lineage Tracking）───────────────────────────

class RetrievalStageLineage(BaseModel):
    """階段一：檢索召回血統"""
    arm: str
    retrieval_latency_ms: float
    retrieved_chunk_ids: List[str] = Field(default_factory=list)
    retrieved_fact_ids: List[str] = Field(default_factory=list)
    hit_exact_spans: List[str] = Field(default_factory=list, description="檢索結果中包含的 gold exact_span")
    missed_exact_spans: List[str] = Field(default_factory=list, description="檢索結果中遺漏的 gold exact_span")
    recall_rate: float = Field(default=0.0, description="召回率 (hit / total essential)")
    retrieved_char_count: int = Field(
        default=0,
        description="組裝後檢索文字總字元數（無空白/換行），供 SNR 計算（報告57 §2.2）",
    )
    snr: float = Field(
        default=0.0,
        description="Signal/Noise Ratio = Σlen(hit_exact_span) / retrieved_char_count（報告57 §2.2）",
    )
    chain_completeness: Optional[float] = Field(
        default=None,
        description=(
            "跨文件推論鏈完整度 = 命中≥1個essential fact的distinct source_law數 / "
            "所需distinct source_law總數；題目只涉及單一source_law時為None（不適用，"
            "非0分，報告57 §2.2）"
        ),
    )


class ContextAssemblyLineage(BaseModel):
    """階段二：Context 組裝血統（排序、截斷、自然語言化）"""
    total_context_tokens: int
    retained_exact_spans: List[str] = Field(default_factory=list, description="最終 Prompt 中仍保留的 exact_span")
    dropped_exact_spans: List[str] = Field(default_factory=list, description="在排序或截斷中被丟棄的 exact_span")
    verbalization_omissions: List[str] = Field(default_factory=list, description="自然語言化遺漏的關鍵細節")


class GenerationStageLineage(BaseModel):
    """階段三：生成與核驗血統"""
    llm_model: str
    generation_latency_ms: float
    raw_draft: str
    grounding_passed: bool
    deterministic_guard_triggered: bool = False
    guard_reasons: List[str] = Field(default_factory=list)
    regenerated: bool = False
    final_output: str
    supported_claims: List[str] = Field(default_factory=list)
    unsupported_claims: List[str] = Field(default_factory=list)


class FullQueryLineage(BaseModel):
    """全鏈路血統記錄物件"""
    query_id: str
    arm: str
    question: str
    stage1_retrieval: RetrievalStageLineage
    stage2_context: ContextAssemblyLineage
    stage3_generation: GenerationStageLineage
    failure_attribution: Optional[str] = Field(default=None, description="瑕疵因果歸因診斷")
