"""禁止斷言與拒答護欄（Refusal Guard，SDD-3.2 交付物）。

對應論文 §3.6 §d 禁止斷言與拒答護欄：
1. 檢索前：超出收錄法規領域（Out-of-Domain）與惡意干擾 Canary 提問識別。
2. 檢索後：零召回（Zero-Retrieval）確定性拒答模板覆寫。
3. 阻斷模型「幻覺硬答」與「編造法條」，零額外生成 Token 浪費。
"""
from __future__ import annotations

import re
from typing import Optional
from pydantic import BaseModel, Field


class RefusalDecision(BaseModel):
    """拒答決策結果"""
    should_refuse: bool = Field(description="是否必須確定性拒答")
    refusal_reason: Optional[str] = Field(default=None, description="觸發拒答之根因")
    standard_refusal_answer: Optional[str] = Field(default=None, description="標準權威拒答語句")


class RefusalGuard:
    """禁止斷言與法定拒答護欄"""

    # 已知超出本系統收錄範圍或荒謬干擾關鍵詞
    OUT_OF_DOMAIN_PATTERNS = [
        re.compile(r"火星|月球|太空旅遊|星際", re.IGNORECASE),
        re.compile(r"(?:億|兆)元罰鍰", re.IGNORECASE),
        re.compile(r"殺人|搶劫|闖紅燈", re.IGNORECASE),
        re.compile(r"刑法第[0-9]+條殺人之罪", re.IGNORECASE),
        re.compile(r"交通管理處罰條例|闖紅燈罰款", re.IGNORECASE),
    ]

    # 標準法定拒答模板
    STANDARD_REFUSAL_TEMPLATE = (
        "依據目前收錄之中華民國勞動法規資料庫，並未記載有關「{topic}」之規定，無法提供確定答覆。"
    )

    @classmethod
    def check_out_of_domain(cls, question: str) -> RefusalDecision:
        """【檢索前調用】檢查惡意/荒謬/超出領域關鍵詞"""
        clean_q = question.strip()
        for pattern in cls.OUT_OF_DOMAIN_PATTERNS:
            if pattern.search(clean_q):
                topic = clean_q[:20] + "..." if len(clean_q) > 20 else clean_q
                return RefusalDecision(
                    should_refuse=True,
                    refusal_reason=f"命中超出領域/干擾模式: {pattern.pattern}",
                    standard_refusal_answer=cls.STANDARD_REFUSAL_TEMPLATE.format(topic=topic),
                )
        return RefusalDecision(should_refuse=False)

    @classmethod
    def check_zero_retrieval(
        cls,
        question: str,
        retrieved_fact_count: int,
        top_similarity: float = 0.0,
    ) -> RefusalDecision:
        """【檢索後調用】檢查檢索是否零召回（且相似度過低）"""
        clean_q = question.strip()
        if retrieved_fact_count == 0 and top_similarity < 0.20:
            topic = clean_q[:20] + "..." if len(clean_q) > 20 else clean_q
            return RefusalDecision(
                should_refuse=True,
                refusal_reason="檢索零召回：法規知識庫中查無任何相關事實，依法定保守原則拒答。",
                standard_refusal_answer=cls.STANDARD_REFUSAL_TEMPLATE.format(topic=topic),
            )
        return RefusalDecision(should_refuse=False)

    @classmethod
    def evaluate_query(
        cls,
        question: str,
        retrieved_fact_count: Optional[int] = None,
        top_similarity: float = 0.0,
    ) -> RefusalDecision:
        """綜合便利入口"""
        ood_dec = cls.check_out_of_domain(question)
        if ood_dec.should_refuse:
            return ood_dec

        if retrieved_fact_count is not None:
            return cls.check_zero_retrieval(question, retrieved_fact_count, top_similarity)

        return RefusalDecision(should_refuse=False)
