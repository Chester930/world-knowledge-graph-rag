"""Deterministic answer-scope audit tests."""

from models.eval_schema import ClaimAuditRule, TestCase as EvalTestCase
from services.claim_scope_auditor import audit_answer_scope


def _case(*rules: ClaimAuditRule) -> EvalTestCase:
    return EvalTestCase(
        id="scope-test",
        question="測試問題",
        source_article="第2條",
        gold_answer="測試答案",
        claim_audit_rules=list(rules),
    )


def test_conditional_claim_requires_explicit_condition():
    case = _case(
        ClaimAuditRule(
            id="head-office",
            kind="conditional",
            trigger_patterns=["五百人"],
            required_condition_patterns=["總機構"],
        )
    )

    missing = audit_answer_scope("第二類事業五百人以上應設一級管理單位。", case)
    present = audit_answer_scope("事業設有總機構時，第二類事業五百人以上應設一級管理單位。", case)

    assert missing["passed"] is False
    assert missing["issues"][0]["missing_conditions"] == ["總機構"]
    assert present["passed"] is True


def test_role_mismatch_rule_does_not_require_llm():
    case = _case(
        ClaimAuditRule(
            id="second-category-role",
            kind="role_mismatch",
            trigger_patterns=["第二類", "五百人", "專責"],
        )
    )

    result = audit_answer_scope("第二類事業五百人以上應設專責一級管理單位。", case)

    assert result == {
        "checked_rule_count": 1,
        "issue_count": 1,
        "issues": [
            {
                "rule_id": "second-category-role",
                "kind": "role_mismatch",
                "description": "",
                "missing_conditions": [],
            }
        ],
        "passed": False,
    }


def test_any_trigger_rule_accepts_one_matching_pattern():
    case = _case(
        ClaimAuditRule(
            id="out-of-scope",
            kind="out_of_scope",
            trigger_patterns=["CNS 45001", "總機構"],
            trigger_mode="any",
        )
    )

    result = audit_answer_scope("另應依 CNS 45001 建置管理系統。", case)

    assert result["passed"] is False
    assert result["issue_count"] == 1


def _bank_case(question_id: str) -> EvalTestCase:
    import json
    from pathlib import Path

    bank = Path(__file__).resolve().parents[2] / "data" / "eval" / "test_cases.json"
    data = json.loads(bank.read_text(encoding="utf-8"))
    row = next(q for q in data["questions"] if q["id"] == question_id)
    return EvalTestCase(**row)


def test_aggr18_swapped_institution_answer_is_flagged_even_when_atomic_facts_present():
    # 2026-09-20 K-arm 基準跑實際觀察到的答案：四個 gold span 的文字都出現，
    # 但新舊法歸屬寫反，Atomic Accuracy 仍為 100%。
    observed_wrong = (
        "新法（勞工職業災害保險及保護法）：\n"
        "- 職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作\n\n"
        "舊法（職業災害勞工保護法）：\n"
        "- 職業災害勞工經醫療終止後，經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作\n\n"
        "因此，新法規定由公立醫療機構認定，而舊法則規定由中央衛生福利主管機關醫院評鑑合格醫院認定。"
    )
    case = _bank_case("57-AGGR18")

    result = audit_answer_scope(observed_wrong, case)

    assert result["passed"] is False
    assert result["issues"][0]["rule_id"] == "aggr18-institution-swapped"


def test_aggr18_gold_answer_and_correct_paraphrase_pass():
    case = _bank_case("57-AGGR18")
    correct_paraphrase = (
        "舊法（職業災害勞工保護法）：\n"
        "- 職業災害勞工經醫療終止後，經公立醫療機構認定身心障礙不堪勝任工作\n\n"
        "新法（勞工職業災害保險及保護法）：\n"
        "- 職業災害勞工經醫療終止後，經中央衛生福利主管機關醫院評鑑合格醫院認定身心障礙不堪勝任工作\n"
    )

    assert audit_answer_scope(case.gold_answer, case)["passed"] is True
    assert audit_answer_scope(correct_paraphrase, case)["passed"] is True
