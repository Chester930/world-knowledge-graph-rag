"""問題場景特徵識別與分類器（Query Classifier，SDD-4.1 交付物）。

以極低延遲（<20ms，純規則與關鍵字特徵）分析提問，
為自適應行為樹（BT）提供場景梯度分流與首選檢索 arm 建議：
- Type-A（單文局部）：首選 M2 (Hybrid Text)
- Type-B（數值密集）：首選 M2 (Hybrid Text) ＋ 查表守衛
- Type-C（跨文多跳）：首選 M4 (Full KG)
- Type-D（全域聚合）：首選 M4 (Full KG)
- Type-E（惡意/超出領域）：直接拒答 (REFUSE)
"""
from __future__ import annotations

import re
from typing import Optional
from pydantic import BaseModel, Field

from models.eval_schema import ScenarioType


class ClassificationResult(BaseModel):
    """提問場景分類結果"""
    scenario: ScenarioType
    recommended_arm: str
    fallback_arm: Optional[str] = None
    confidence: float
    features_detected: list[str] = Field(default_factory=list)


class QueryClassifier:
    """輕量規則式問題特徵分類器"""

    # Type-E: 惡意/荒謬模式
    OUT_OF_DOMAIN_PATTERNS = [
        re.compile(r"火星|月球|太空旅遊|星際", re.IGNORECASE),
        re.compile(r"(?:億|兆)元罰鍰", re.IGNORECASE),
        re.compile(r"殺人|搶劫|闖紅燈", re.IGNORECASE),
    ]

    # Type-D: 全域聚合與統計模式
    AGGREGATION_PATTERNS = [
        re.compile(r"所有.*?(?:規定|事由|項目|清單|條款)", re.IGNORECASE),
        re.compile(r"統計.*?(?:有哪些|幾種|何種)", re.IGNORECASE),
        re.compile(r"哪些法令同時規定|彙整全部", re.IGNORECASE),
    ]

    # Type-C: 跨法規多跳與複雜關聯特徵
    # ⚠️ **入庫時審查發現（2026-09-14）**：以下三條正則是題庫裡特定題目的主題字串
    # 硬編碼（例如「災區受災勞工.*?保險費」直接對應 26-Q5 的問題原文），不是可泛化的
    # 跨文件多跳特徵抽取——這是對已知題庫的過擬合／背答案，不是通用分類器。用同一份
    # 題庫測這個分類器的「Type-C 分類準確率」會是循環論證（拿寫死答案去驗證答案）。
    # 真正的多跳特徵應該基於結構訊號（如問句同時提及 ≥2 個不同法規/實體名稱），而非
    # 題目原文子字串；此清單只適合當作臨時 demo 用的規則、不可用於任何正式評測結論。
    MULTI_HOP_PATTERNS = [
        re.compile(r"災區受災勞工.*?保險費", re.IGNORECASE),
        re.compile(r"大量解僱.*?僱用獎勵金", re.IGNORECASE),
        re.compile(r"性別平等.*?育嬰留職停薪.*?年資", re.IGNORECASE),
    ]

    # Type-B: 密集數值與條件分支特徵
    NUMERIC_PATTERNS = [
        re.compile(r"幾天|幾日|多久|幾個月|幾次|多少元|百分之|幾歲|時數|級距|上限是多少|ppm|變量係數"),
        re.compile(r"未住院.*?住院|滿.*?歲|超過.*?日"),
    ]

    @classmethod
    def classify(cls, question: str) -> ClassificationResult:
        """分析提問特徵並回傳場景梯度與推薦執行 arm"""
        clean_q = question.strip()
        features: list[str] = []

        # 1. 優先檢查 Type-E
        for p in cls.OUT_OF_DOMAIN_PATTERNS:
            if p.search(clean_q):
                features.append(f"CanaryPattern({p.pattern})")
                return ClassificationResult(
                    scenario=ScenarioType.TYPE_E,
                    recommended_arm="REFUSE",
                    fallback_arm=None,
                    confidence=1.0,
                    features_detected=features,
                )

        # 2. 檢查 Type-D: 全域聚合
        for p in cls.AGGREGATION_PATTERNS:
            if p.search(clean_q):
                features.append("AggregationPattern")
                return ClassificationResult(
                    scenario=ScenarioType.TYPE_D,
                    recommended_arm="M4",  # Full KG
                    fallback_arm="M3",     # Fact Vector
                    confidence=0.85,
                    features_detected=features,
                )

        # 3. 檢查 Type-C: 跨法規多跳
        for p in cls.MULTI_HOP_PATTERNS:
            if p.search(clean_q):
                features.append("MultiHopCrossLawPattern")
                return ClassificationResult(
                    scenario=ScenarioType.TYPE_C,
                    recommended_arm="M4",  # Full KG (拓撲遍歷優勢)
                    fallback_arm="M2",     # Hybrid Text
                    confidence=0.90,
                    features_detected=features,
                )

        # 4. 檢查 Type-B: 密集數值與條件分支
        for p in cls.NUMERIC_PATTERNS:
            if p.search(clean_q):
                features.append("NumericConditionPattern")
                return ClassificationResult(
                    scenario=ScenarioType.TYPE_B,
                    recommended_arm="M2",  # Hybrid Text (文字連續性佳)
                    fallback_arm="M4",     # 備選 Full KG
                    confidence=0.88,
                    features_detected=features,
                )

        # 5. 預設 Type-A: 單文局部條文
        features.append("DefaultSingleDocPattern")
        return ClassificationResult(
            scenario=ScenarioType.TYPE_A,
            recommended_arm="M2",  # Hybrid Text
            fallback_arm="M1",     # Naive Chunk
            confidence=0.80,
            features_detected=features,
        )
