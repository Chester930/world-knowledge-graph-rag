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
