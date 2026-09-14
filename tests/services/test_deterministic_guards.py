"""單元測試：確定性接地守衛與拒答護欄（SDD-3.1 & SDD-3.2）。

驗證：
1. 起算日錨點守衛：攔截「當月一日」被平滑化為「當日」（26-Q5）。
2. 起算日錨點守衛：放行精確包含「當月一日」之合法答案。
3. 條號守衛：攔截未引證之捏造條號（如 context 只有第 2 條，草稿捏造第 38 條）。
4. 條號守衛：放行引用合法條號之草稿。
5. 拒答護欄：直接命中超出領域 Canary（火星、超額億元罰鍰）並回傳權威拒答。
6. 拒答護欄：檢索零召回時強制拒答。
"""
import pytest
from services.deterministic_guard_service import DeterministicGuardService
from services.refusal_guard import RefusalGuard


def test_inception_anchor_guard_catches_smoothing():
    context = (
        "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月。"
        "其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"
    )

    # 瑕疵草稿：把「當月一日」平滑化為「當日」
    smoothed_draft = "災後六個月期間由中央政府支應，其期間自災害發生當日起計算六個月。"

    res = DeterministicGuardService.verify_draft(
        context_text=context,
        fact_lines=[context],
        question="災區受災勞工保費補助期間從哪一天起算？",
        draft_answer=smoothed_draft,
    )

    assert res.is_valid is False
    assert res.guard_name == "InceptionAnchorGuard"
    assert "語意平滑化漏洞" in res.failure_reason
    assert "當月一日" in res.extra_constrained_note


def test_inception_anchor_guard_passes_exact_date():
    context = (
        "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月。"
        "其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"
    )

    # 合法草稿：保留「當月一日」
    exact_draft = "受災勞工保費由中央政府支應，自災害發生之當月一日起計算六個月。"

    res = DeterministicGuardService.verify_draft(
        context_text=context,
        fact_lines=[context],
        question="災區受災勞工保費補助期間從哪一天起算？",
        draft_answer=exact_draft,
    )

    assert res.is_valid is True
    assert res.guard_name is None


def test_article_span_guard_catches_hallucination():
    context = "勞工結婚者給予婚假八日，工資照給。"
    allowed_articles = ["N0030006 勞工請假規則 第2條"]

    # 捏造條號：草稿宣稱「依勞動基準法第38條」
    hallucinated_draft = "依據勞動基準法第38條規定，勞工結婚可請婚假八日。"

    res = DeterministicGuardService.verify_draft(
        context_text=context,
        fact_lines=[context],
        question="勞工結婚可以請幾天婚假？",
        draft_answer=hallucinated_draft,
        allowed_articles=allowed_articles,
    )

    assert res.is_valid is False
    assert res.guard_name == "ArticleSpanGuard"
    assert "條號幻覺" in res.failure_reason
    assert "第38條" in res.failure_reason


def test_article_span_guard_passes_valid_article():
    context = "勞工結婚者給予婚假八日，工資照給。"
    allowed_articles = ["N0030006 勞工請假規則 第2條"]

    valid_draft = "依據勞工請假規則第2條規定，勞工結婚者給予婚假八日，工資照給。"

    res = DeterministicGuardService.verify_draft(
        context_text=context,
        fact_lines=[context],
        question="勞工結婚可以請幾天婚假？",
        draft_answer=valid_draft,
        allowed_articles=allowed_articles,
    )

    assert res.is_valid is True


def test_refusal_guard_out_of_domain():
    # 測試惡意/超出領域問題
    q1 = "請問勞工每工作五年，雇主是否應補助至火星旅遊考察？"
    dec1 = RefusalGuard.evaluate_query(q1)
    assert dec1.should_refuse is True
    assert "超出領域" in dec1.refusal_reason
    assert "未記載" in dec1.standard_refusal_answer

    q2 = "請問違反法令最高可處新臺幣五十億元罰鍰嗎？"
    dec2 = RefusalGuard.evaluate_query(q2)
    assert dec2.should_refuse is True
    assert "超出領域" in dec2.refusal_reason


def test_refusal_guard_zero_retrieval():
    # 測試正常問題但檢索零召回
    q = "某極端罕見且庫存無資料的特定補助規定？"
    dec = RefusalGuard.evaluate_query(q, retrieved_fact_count=0, top_similarity=0.05)
    assert dec.should_refuse is True
    assert "檢索零召回" in dec.refusal_reason
    assert "並未記載" in dec.standard_refusal_answer
