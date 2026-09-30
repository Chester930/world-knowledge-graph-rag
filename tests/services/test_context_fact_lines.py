from __future__ import annotations

import ast
from pathlib import Path

from routers import agent


def test_reexported_names_are_the_same_function_objects():
    from services.context import fact_lines

    assert agent._strip_type_markers is fact_lines.strip_type_markers
    assert agent._is_contentful_line is fact_lines.is_contentful_line
    assert agent._litm_reorder is fact_lines.litm_reorder


def test_strip_type_markers_cases():
    from services.context import fact_lines

    cases = [
        ("（概念）", ""),
        ("（PERSON,PERSON）", ""),
        ("（PERSON, PERSON）", ""),
        ("PERSON", ""),
        ("XORGANIZATION", "XORGANIZATION"),
        ("  勞工 PERSON  ", "勞工"),
        ("普通文字", "普通文字"),
        ("(PERSON,PERSON)", "()"),
    ]

    assert [fact_lines.strip_type_markers(value) for value, _ in cases] == [
        expected for _, expected in cases
    ]


def test_is_contentful_line_cases():
    from services.context import fact_lines

    cases = [
        ("", "S", False),
        ("- ", "S", False),
        (" S ", "S", False),
        ("- S ", "S", False),
        ("- S 發生", "S", True),
        ("- 內容", None, True),
        ("- S（PERSON）", "S", False),
        ("- （PERSON）內容", None, True),
    ]

    assert [fact_lines.is_contentful_line(line, subject) for line, subject, _ in cases] == [
        expected for _, _, expected in cases
    ]


def test_litm_reorder_cases():
    from services.context import fact_lines

    cases = [
        ([], []),
        ([1], [1]),
        ([1, 2], [2, 1]),
        ([1, 2, 3], [1, 3, 2]),
        ([1, 2, 3, 4], [2, 4, 3, 1]),
        ([1, 2, 3, 4, 5], [1, 3, 5, 4, 2]),
    ]

    for values, expected in cases:
        original = list(values)
        result = fact_lines.litm_reorder(values)
        assert result == expected
        assert values == original
        assert result is not values


def test_fact_lines_module_has_no_reverse_dependency():
    from services.context import fact_lines

    tree = ast.parse(Path(fact_lines.__file__).read_text(encoding="utf-8"))
    top_level_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_modules.add(node.module.split(".")[0])

    assert top_level_modules <= {"re", "core"}
    assert "routers" not in top_level_modules
    assert "services" not in top_level_modules
