"""W0 pure tests for the G1 scheme-B harness; Docker is never required."""

from __future__ import annotations

import ast
from uuid import uuid4

import pytest

from scripts.analysis.disposable_resync_solution_b_validation import (
    EXPECTED_KG4_STARTED_AT,
    IMAGE,
    TEMP_CONTAINER,
    _plan_resync_updates,
    build_docker_run_argv,
    generate_temp_password,
    validate_connection_target,
)


def test_new_started_at_baseline_is_the_post_restart_value():
    assert EXPECTED_KG4_STARTED_AT == "2026-10-02T04:10:38.389676557Z"


def test_gate_accepts_only_the_throwaway_bolt_endpoint():
    validate_connection_target("bolt://127.0.0.1:27687", uuid4())


@pytest.mark.parametrize(
    "uri",
    ["bolt://localhost:17990", "bolt://127.0.0.1:7687", "http://localhost:27687", "bolt://kg2-neo4j:27687"],
)
def test_gate_rejects_protected_or_wrong_targets(uri):
    with pytest.raises(RuntimeError):
        validate_connection_target(uri, uuid4())


def test_docker_arguments_remain_fixed_without_mount_or_pull():
    argv = build_docker_run_argv()
    assert argv[0] == "run"
    assert TEMP_CONTAINER in argv
    assert IMAGE in argv
    assert "27474:7474" in argv and "27687:7687" in argv and "3g" in argv
    assert "--pull" not in argv
    assert not {"--mount", "-v", "--network", "--privileged"}.intersection(argv)
    assert "neo4j/" not in " ".join(argv)


def test_password_is_random_and_not_in_command_arguments():
    first = generate_temp_password()
    second = generate_temp_password()
    assert first != second
    assert first not in " ".join(build_docker_run_argv())


def test_pure_resync_planner_counts_changes_and_conservative_edges():
    rows = [
        {
            "eid": "1", "flat_subject": "舊", "flat_object": "物", "flat_rel_type": "OLD",
            "subject_exists": True, "object_exists": True, "subject_name": "新", "object_name": "物",
            "edge_count": 1, "edge_types": ["NEW"],
        },
        {
            "eid": "2", "flat_subject": "新", "flat_object": "物", "flat_rel_type": "OLD",
            "subject_exists": True, "object_exists": True, "subject_name": "新", "object_name": "物",
            "edge_count": 2, "edge_types": ["A", "B"],
        },
        {
            "eid": "3", "flat_subject": "舊", "flat_object": "物", "flat_rel_type": "OLD",
            "subject_exists": True, "object_exists": True, "subject_name": "新", "object_name": "物",
            "edge_count": 0, "edge_types": [],
        },
        {
            "eid": "4", "flat_subject": "舊", "flat_object": "物", "flat_rel_type": "OLD",
            "subject_exists": False, "object_exists": True, "subject_name": None, "object_name": "物",
            "edge_count": 0, "edge_types": [],
        },
    ]
    stats, updates = _plan_resync_updates(rows, sync_rel_type=True)
    assert stats == {
        "subject_changed": 2,
        "object_changed": 0,
        "rel_type_changed": 1,
        "rel_type_skipped_multi_edge": 1,
        "rel_type_skipped_no_edge": 1,
        "unchanged": 1,
        "facts_without_links": 1,
    }
    assert {row["eid"] for row in updates["subject"]} == {"1", "3"}
    assert updates["rel_type"] == [{"eid": "1", "value": "NEW"}]


def test_new_harness_never_defines_or_calls_old_baseline_runners():
    source = ast.parse(open("scripts/analysis/disposable_resync_solution_b_validation.py", encoding="utf-8").read())
    function_names = {node.name for node in ast.walk(source) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_run_with_password" not in function_names
    assert "run_with_password" not in function_names
    text = open("scripts/analysis/disposable_resync_solution_b_validation.py", encoding="utf-8").read()
    assert "p3._run_with_password" not in text
    assert "p4.run_with_password" not in text
