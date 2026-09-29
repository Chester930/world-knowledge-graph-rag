"""Structural and characterization guards for report 126 SM-1 wiring."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from services import document_record_service as svc


def _status_assignments() -> list[tuple[str, str, int]]:
    source_path = Path(svc.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assignments: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Attribute):
                continue
            if target.attr not in {"extraction_status", "normalization_status"}:
                continue
            containing = [
                function
                for function in functions
                if function.lineno <= node.lineno <= function.end_lineno
            ]
            assert containing, f"status assignment has no containing function: line {node.lineno}"
            function = min(containing, key=lambda item: item.end_lineno - item.lineno)
            assignments.append((target.attr, function.name, node.lineno))
    return assignments


def test_status_assignments_have_single_private_entrypoint():
    assignments = _status_assignments()
    assert assignments
    unexpected = [
        item
        for item in assignments
        if (
            item[0] == "extraction_status"
            and item[1] != "_transition_extraction"
        )
        or (
            item[0] == "normalization_status"
            and item[1] != "_transition_normalization"
        )
    ]
    assert not unexpected, f"status assignments escaped single entrypoints: {unexpected}"


def test_illegal_normalization_status_preserves_raw_write_without_early_value_error(tmp_path):
    svc.init_record(tmp_path, source="legacy.md", total_chunks=1)

    result = svc.update_normalization_progress(
        tmp_path,
        status="legacy_invalid",  # type: ignore[arg-type]
        progress=0,
    )

    raw = json.loads((tmp_path / "_record.json").read_text(encoding="utf-8"))
    assert result.normalization_status == "legacy_invalid"
    assert raw["normalization_status"] == "legacy_invalid"


def test_init_record_total_change_still_resets_normalization_status(tmp_path):
    svc.init_record(tmp_path, source="reparse.md", total_chunks=2)
    svc.update_normalization_progress(
        tmp_path, status="completed", progress=2, total_sentences=2,
    )
    svc.set_svo_chunk_total(tmp_path, 4)

    result = svc.init_record(tmp_path, source="reparse.md", total_chunks=3)
    raw = json.loads((tmp_path / "_record.json").read_text(encoding="utf-8"))

    assert result.normalization_status == "not_started"
    assert raw["normalization_status"] == "not_started"
    assert raw["normalization_progress"] == 0
    assert raw["normalization_total_sentences"] == 0
    assert raw["svo_total_chunks"] == 0
