"""V0 tests for the P4 validation harness; Docker is opt-in only."""

from __future__ import annotations

import ast
from uuid import uuid4

import pytest

from scripts.analysis.disposable_write_path_validation import (
    EXPECTED_KG4_STARTED_AT,
    IMAGE,
    KG4_ID,
    TEMP_CONTAINER,
    build_docker_run_argv,
    generate_temp_password,
    validate_connection_target,
)


def test_new_started_at_baseline_is_the_report_242_value():
    assert EXPECTED_KG4_STARTED_AT == "2026-10-02T04:10:38.389676557Z"


def test_connection_gate_accepts_only_throwaway_bolt_target():
    validate_connection_target("bolt://127.0.0.1:27687", uuid4())
    validate_connection_target("bolt://localhost:27687", uuid4())


@pytest.mark.parametrize(
    "uri",
    ["bolt://localhost:17990", "bolt://127.0.0.1:7687", "http://localhost:27687", "bolt://kg2-neo4j:27687"],
)
def test_connection_gate_rejects_protected_or_wrong_targets(uri):
    with pytest.raises(RuntimeError):
        validate_connection_target(uri, uuid4())


def test_connection_gate_rejects_protected_kg_id():
    with pytest.raises(RuntimeError):
        validate_connection_target("bolt://127.0.0.1:27687", KG4_ID)


def test_docker_run_arguments_are_fixed_and_have_no_mount_or_privilege_flags():
    argv = build_docker_run_argv()
    assert argv[0] == "run"
    assert TEMP_CONTAINER in argv
    assert IMAGE in argv
    assert "27474:7474" in argv
    assert "27687:7687" in argv
    assert "3g" in argv
    assert "--privileged" not in argv
    assert "--mount" not in argv
    assert "-v" not in argv
    assert "--network" not in argv
    assert "--restart" not in argv
    assert "neo4j/" not in " ".join(argv)


def test_temp_password_is_random_and_not_in_run_arguments():
    first = generate_temp_password()
    second = generate_temp_password()
    assert first != second
    assert first not in " ".join(build_docker_run_argv())


def test_old_p3_runner_is_not_called_or_redefined():
    source = ast.parse(open("scripts/analysis/disposable_write_path_validation.py", encoding="utf-8").read())
    names = {node.name for node in ast.walk(source) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_run_with_password" not in names
    assert "p3._run_with_password" not in open(
        "scripts/analysis/disposable_write_path_validation.py", encoding="utf-8"
    ).read()
