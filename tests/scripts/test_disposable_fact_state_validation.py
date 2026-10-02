"""P3 T0 gates and proposal ordering tests; Docker is opt-in only."""

from __future__ import annotations

from uuid import uuid4

import pytest

from scripts.analysis.disposable_fact_state_validation import (
    IMAGE,
    KG4_ID,
    TEMP_CONTAINER,
    build_docker_run_argv,
    generate_temp_password,
    proposal_filter_then_dedupe,
    validate_connection_target,
)
from services import relation_lifecycle as rl


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


def test_proposal_filters_lifecycle_before_existing_key_dedupe():
    records = [
        {"fixture_id": "superseded", "subject": "A", "rel_type": "R", "object": "B", "lifecycle_state": rl.SUPERSEDED, "score": 1.0},
        {"fixture_id": "valid", "subject": "A", "rel_type": "R", "object": "B", "lifecycle_state": rl.VALID, "score": 0.8},
    ]
    selected = proposal_filter_then_dedupe(records)
    assert [record["fixture_id"] for record in selected] == ["valid"]

