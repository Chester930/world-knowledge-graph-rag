"""Pure safety-gate tests for the G2 disposable backup/restore harness."""

from __future__ import annotations

import inspect

import pytest

from scripts.analysis import disposable_backup_restore_validation as g2


def test_started_at_is_the_post_restart_baseline():
    assert g2.EXPECTED_KG4_STARTED_AT == "2026-10-02T04:10:38.389676557Z"


def test_only_the_two_exact_container_names_are_allowed():
    g2.validate_container_name(g2.SOURCE_CONTAINER)
    g2.validate_container_name(g2.RESTORE_CONTAINER)
    for name in ("kg2-neo4j", "evil-throwaway", "kg2-throwaway-other"):
        with pytest.raises(g2.GateViolation):
            g2.validate_container_name(name)


def test_volume_gate_accepts_prefix_and_rejects_protected_or_other_names():
    g2.validate_volume_name("kg2-throwaway-data")
    with pytest.raises(g2.GateViolation):
        g2.validate_volume_name("kg2_neo4j_data")
    with pytest.raises(g2.GateViolation):
        g2.validate_volume_name("kg_neo4j_data")
    with pytest.raises(g2.GateViolation):
        g2.validate_volume_name("zion_neo4j_data")


def test_temp_path_gate_is_exactly_the_dedicated_host_directory():
    g2.validate_temp_path(g2.TEMP_ROOT)
    g2.validate_temp_path(g2.TEMP_ROOT / "method-a" / "neo4j.dump")
    with pytest.raises(g2.GateViolation):
        g2.validate_temp_path(g2._REPO / "backup.dump")


def test_run_gate_requires_fixed_image_memory_names_and_safe_mounts():
    args = g2._server_run_args(g2.SOURCE_CONTAINER, g2.SOURCE_VOLUME)
    g2.validate_docker_run_args(args)
    forbidden = list(args)
    forbidden[forbidden.index("-v") + 1] = "kg2_neo4j_data:/data"
    with pytest.raises(g2.GateViolation):
        g2.validate_docker_run_args(forbidden)
    forbidden_pull = list(args) + ["--pull=always"]
    with pytest.raises(g2.GateViolation):
        g2.validate_docker_run_args(forbidden_pull)


def test_helper_mount_gate_allows_only_throwaway_volume_and_dedicated_temp_path():
    args = g2._admin_hold_args(g2.RESTORE_CONTAINER, g2.RESTORE_VOLUME)
    g2.validate_docker_run_args(args)
    tar_args = [
        "run", "--name", g2.SOURCE_CONTAINER, "--memory", "3g",
        "-v", f"{g2.SOURCE_VOLUME}:/data:ro", "-v", f"{g2.TEMP_ROOT}:/backup",
        "--entrypoint", "tar", g2.IMAGE, "-czf", "/backup/data.tar.gz", "-C", "/data", ".",
    ]
    g2.validate_docker_run_args(tar_args)
    tar_args[tar_args.index("-v") + 1] = "kg_neo4j_data:/data:ro"
    with pytest.raises(g2.GateViolation):
        g2.validate_docker_run_args(tar_args)


def test_cp_gate_requires_one_exact_container_and_the_dedicated_temp_path():
    g2.validate_docker_cp_args(["cp", f"{g2.SOURCE_CONTAINER}:/tmp/g2-a/.", str(g2.TEMP_ROOT / "method-a")])
    g2.validate_docker_cp_args(["cp", str(g2.TEMP_ROOT / "method-b" / "neo4j.dump"), f"{g2.RESTORE_CONTAINER}:/tmp/load/neo4j.dump"])
    with pytest.raises(g2.GateViolation):
        g2.validate_docker_cp_args(["cp", "kg2-neo4j:/data", str(g2.TEMP_ROOT / "bad")])
    with pytest.raises(g2.GateViolation):
        g2.validate_docker_cp_args(["cp", f"{g2.SOURCE_CONTAINER}:/data", f"{g2.RESTORE_CONTAINER}:/data"])


def test_exec_gate_rejects_protected_container_reference():
    g2.validate_docker_exec_args(["exec", g2.SOURCE_CONTAINER, "neo4j-admin", "database", "backup"])
    with pytest.raises(g2.GateViolation):
        g2.validate_docker_exec_args(["exec", g2.SOURCE_CONTAINER, "sh", "-c", "echo kg2-neo4j"])


def test_new_harness_does_not_define_or_call_old_baseline_runners():
    source = inspect.getsource(g2)
    assert "_run_with_password" not in source
    assert "run_with_password" not in source
    assert "kg2-neo4j" in source  # only gate/error evidence; no protected run target

