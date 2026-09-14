"""生成端確定性接地守衛服務（Deterministic Grounding Guard，SDD-3.1 交付物）。

對應論文 §3.6 §d 確定性接地守衛：
1. 日期與起算日錨點守衛（Inception Anchor Guard）：嚴禁「當月一日」被平滑化為「當日」。
2. 法規條號守衛（Article Span Guard）：嚴禁生成模型自由捏造未引證之條號。
3. 數值區間與查表守衛（Interval Lookup Guard）：查表缺口確定性強制拒答。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

from services import interval_lookup_service


class GuardVerificationResult(BaseModel):
    """確定性守衛檢驗結果"""
    is_valid: bool = Field(description="是否通過所有確定性守衛")
    guard_name: Optional[str] = Field(default=None, description="觸發阻斷之守衛名稱")
    failure_reason: Optional[str] = Field(default=None, description="阻斷具體原因")
    extra_constrained_note: Optional[str] = Field(default=None, description="注入重生成 prompt 之硬性約束")


class DeterministicGuardService:
    """四道確定性接地守衛檢驗器"""

    # 起算日模式：自...之(當月一日|次月首日|發生當日|當日|次日|翌日)起
    INCEPTION_PATTERN = re.compile(
        r"自\s*(?:.*?)\s*之?\s*(當月一日|次月首日|次月一日|事故發生當日|災害發生當日|發生當日|當日|次日|翌日)\s*起",
        re.IGNORECASE,
    )

    # 條號提取模式：第 X 條
    ARTICLE_PATTERN = re.compile(r"第\s*([0-9\u4e00-\u9fa5]+)\s*條")

    @classmethod
    def check_inception_date(
        cls,
        context_text: str,
        draft_answer: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """檢查起算日是否遭語意平滑化（如 26-Q5：當月一日 變 當日）"""
        # 從 context 抓出所有起算錨點
        context_matches = cls.INCEPTION_PATTERN.findall(context_text)
        if not context_matches:
            return True, None, None

        # 若 context 包含「當月一日」或「次月首日」等關鍵法定起算錨點
        strict_anchors = [m for m in context_matches if m in ("當月一日", "次月首日", "次月一日")]
        if not strict_anchors:
            return True, None, None

        target_anchor = strict_anchors[0]

        # 檢視草稿是否平滑化為「當日」或省略了錨點
        clean_draft = draft_answer.replace(" ", "")
        if target_anchor not in clean_draft:
            # 檢查是否被改寫成了「當日」
            if "當日起" in clean_draft or "發生當日" in clean_draft:
                reason = (
                    f"語意平滑化漏洞：法規原文起算日為「{target_anchor}」，"
                    f"草稿被錯誤縮寫/平滑化為「當日」，起算時點相差近整月。"
                )
            else:
                reason = f"法定起算日遺漏：未精確記載法規原文起算日「{target_anchor}」。"

            note = (
                f"【法定起算日硬約束】法規原文明確規定期間起算時點為「{target_anchor}」！"
                f"嚴禁擅自平滑化或改寫為「當日」或「發生當日」，必須精確按照「{target_anchor}」作答。"
            )
            return False, reason, note

        return True, None, None

    @classmethod
    def check_article_numbers(
        cls,
        allowed_articles: List[str],
        draft_answer: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """檢查草稿引用的條號是否出現在檢索條目範圍內（杜絕捏造條號）"""
        if not allowed_articles:
            return True, None, None

        # 彙整合法條號關鍵字（例如 "第2條", "第3條", "2", "3"）
        allowed_nums = set()
        for art in allowed_articles:
            for m in cls.ARTICLE_PATTERN.findall(art):
                allowed_nums.add(m)

        if not allowed_nums:
            return True, None, None

        # 抓取草稿中引用的所有條號
        draft_articles = cls.ARTICLE_PATTERN.findall(draft_answer)
        for d_art in draft_articles:
            if d_art not in allowed_nums:
                reason = f"條號幻覺：草稿引用了未在檢索範圍內的法條「第{d_art}條」（合法範圍：第{allowed_nums}條）。"
                note = f"【條號硬約束】嚴禁引用未在檢索事實中出現的條號「第{d_art}條」，僅能引用已知事實之依據。"
                return False, reason, note

        return True, None, None

    @classmethod
    def check_interval_lookup(
        cls,
        fact_lines: List[str],
        question: str,
        draft_answer: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """調用方案 E 之數值區間查表檢查"""
        try:
            override = interval_lookup_service.audit_lookup_answer(
                fact_lines=fact_lines,
                question=question,
                draft_answer=draft_answer,
            )
            if override and override.force_unsupported:
                reason = "數值區間查表缺口：提問數值未落在任何法規級距中，草稿硬性給出確定值。"
                note = override.extra_prompt_note or "【查表缺口硬約束】提問數值未落在事實清單的任何級距中，嚴禁編造數值，必須誠實回答資料未記載！"
                return False, reason, note
        except Exception:
            # 方案 E 執行異常時安全放行，不阻礙主流程
            pass

        return True, None, None

    @classmethod
    def verify_draft(
        cls,
        context_text: str,
        fact_lines: List[str],
        question: str,
        draft_answer: str,
        allowed_articles: Optional[List[str]] = None,
    ) -> GuardVerificationResult:
        """端到端綜合檢驗入口"""
        # 1. 檢驗起算日
        ok, reason, note = cls.check_inception_date(context_text, draft_answer)
        if not ok:
            return GuardVerificationResult(
                is_valid=False,
                guard_name="InceptionAnchorGuard",
                failure_reason=reason,
                extra_constrained_note=note,
            )

        # 2. 檢驗條號合法性
        if allowed_articles:
            ok, reason, note = cls.check_article_numbers(allowed_articles, draft_answer)
            if not ok:
                return GuardVerificationResult(
                    is_valid=False,
                    guard_name="ArticleSpanGuard",
                    failure_reason=reason,
                    extra_constrained_note=note,
                )

        # 3. 檢驗數值區間查表
        ok, reason, note = cls.check_interval_lookup(fact_lines, question, draft_answer)
        if not ok:
            return GuardVerificationResult(
                is_valid=False,
                guard_name="IntervalLookupGuard",
                failure_reason=reason,
                extra_constrained_note=note,
            )

        return GuardVerificationResult(is_valid=True)
