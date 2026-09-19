"""Deterministic offline audit for answer scope and conditional claims.

The auditor is intentionally separate from ``AtomicScorer``.  Atomic scoring
answers whether required facts are present; this module checks whether an
answer also introduces a claim outside the question's declared scope or drops a
condition/role distinction declared by the test case.
"""

from __future__ import annotations

import re
from typing import Any

from models.eval_schema import ClaimAuditRule, TestCase


def _normalize(text: str) -> str:
    """Normalize only whitespace and case so Chinese punctuation remains safe."""

    return re.sub(r"\s+", "", text or "").casefold()


def _matches(patterns: list[str], text: str, mode: str) -> bool:
    normalized = _normalize(text)
    hits = [_normalize(pattern) in normalized for pattern in patterns if pattern]
    if not hits:
        return False
    return all(hits) if mode == "all" else any(hits)


def audit_answer_scope(answer: str, test_case: TestCase) -> dict[str, Any]:
    """Return deterministic scope-risk events for one saved answer.

    A conditional rule passes only when its trigger is absent or every declared
    condition is explicitly present in the answer.  The function never calls an
    LLM and never changes the atomic score.
    """

    issues: list[dict[str, Any]] = []
    for rule in test_case.claim_audit_rules:
        if not _matches(rule.trigger_patterns, answer, rule.trigger_mode):
            continue
        missing_conditions = [
            pattern
            for pattern in rule.required_condition_patterns
            if _normalize(pattern) not in _normalize(answer)
        ]
        if rule.kind == "conditional" and not missing_conditions:
            continue
        issues.append(
            {
                "rule_id": rule.id,
                "kind": rule.kind,
                "description": rule.description,
                "missing_conditions": missing_conditions,
            }
        )

    return {
        "checked_rule_count": len(test_case.claim_audit_rules),
        "issue_count": len(issues),
        "issues": issues,
        "passed": not issues,
    }
