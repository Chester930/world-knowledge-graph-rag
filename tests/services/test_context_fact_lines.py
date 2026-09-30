from __future__ import annotations

import ast
from pathlib import Path

import pytest

from models.knowledge_graph import SVOTriple
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

    assert top_level_modules <= {"re", "core", "models"}
    assert "routers" not in top_level_modules
    assert "services" not in top_level_modules
    assert "repositories" not in top_level_modules


def _context_triple(subject="A", rel_type="RELATED_TO", object_="B", verb="導致", natural_text=None):
    return SVOTriple(
        subject=subject,
        subject_type="概念",
        rel_type=rel_type,
        verb=verb,
        object=object_,
        object_type="概念",
        natural_text=natural_text,
    )


def test_split_merge_reexported_as_same_function_objects():
    from services.context import fact_lines

    assert agent._split_fact_lines is fact_lines.split_fact_lines
    assert agent._merge_fact_lines is fact_lines.merge_fact_lines


@pytest.mark.parametrize(
    ("name", "triples", "fact_results", "prefer", "expected_bfs", "expected_fact"),
    [
        ("basic_bfs", [_context_triple("A", "CAUSES", "B", "導致", "A 導致 B")], [], False,
         ["- A 導致 B"], []),
        ("basic_fact", [], [{"fact_text": "C 需要 D", "subject": "C", "rel_type": "REQUIRES", "object": "D", "verb": "需要"}], False,
         [], ["- C 需要 D"]),
        ("collision_default", [_context_triple("A", "REL", "B", "BFS", "A BFS B")], [{"fact_text": "A FACT B", "subject": "A", "rel_type": "REL", "object": "B", "verb": "FACT"}], False,
         ["- A BFS B"], []),
        ("collision_prefer_fact", [_context_triple("A", "REL", "B", "BFS", "A BFS B")], [{"fact_text": "A FACT B", "subject": "A", "rel_type": "REL", "object": "B", "verb": "FACT"}], True,
         [], ["- A FACT B"]),
        ("object_empty_text_collision", [_context_triple("S", "REL", "", "以內容", "S 以內容")], [{"fact_text": "S 以內容", "subject": "S", "rel_type": "REL", "object": "", "verb": "以內容"}], False,
         ["- S 以內容"], []),
        ("empty_subjects_and_valid", [_context_triple("", "REL", "B", "有")], [{"fact_text": "  ", "subject": "   ", "rel_type": "REL", "object": "B", "verb": "有"}, {"fact_text": "V 有 W", "subject": "V", "rel_type": "REL", "object": "W", "verb": "有"}], False,
         [], ["- V 有 W"]),
        ("empty_fact_verb_prefer", [_context_triple("S", "REL", "O", "自然", "S 自然 O")], [{"fact_text": "S  O", "subject": "S", "rel_type": "REL", "object": "O", "verb": ""}], True,
         ["- S 自然 O"], []),
        ("markers", [_context_triple("A", "REL", "B", "是", "A（概念） 是 B（PERSON,PERSON）")], [{"fact_text": "A（概念） 是 B（PERSON,PERSON）", "subject": "A", "rel_type": "REL", "object": "B", "verb": "是"}], False,
         ["- A 是 B"], []),
        ("subject_only", [_context_triple("S", "REL", "", "", None)], [{"fact_text": "S（概念）  （概念）", "subject": "S", "rel_type": "REL", "object": "", "verb": ""}], False,
         [], []),
        ("duplicate_rendered_text", [_context_triple("S", "REL1", "", "", "S same"), _context_triple("T", "REL2", "", "", "S same")], [], False,
         ["- S same"], []),
        ("missing_fact_keys", [_context_triple("A", "REL", "B", "有", "A 有 B")], [{"fact_text": "舊資料事實", "subject": None, "rel_type": None, "object": None}], False,
         ["- A 有 B"], ["- 舊資料事實"]),
        ("mixed", [_context_triple("A", "R1", "B", "一", "A 一 B"), _context_triple("X", "R2", "", "以", "X 以")], [{"fact_text": "A 二 B", "subject": "A", "rel_type": "R1", "object": "B", "verb": "二"}, {"fact_text": "Y 三 Z", "subject": "Y", "rel_type": "R3", "object": "Z", "verb": "三"}], True,
         ["- X 以"], ["- A 二 B", "- Y 三 Z"]),
    ],
)
def test_split_fact_lines_cases(name, triples, fact_results, prefer, expected_bfs, expected_fact):
    from services.context import fact_lines

    assert name
    assert fact_lines.split_fact_lines(
        triples, fact_results, prefer_fact_on_collision=prefer,
    ) == (expected_bfs, expected_fact)


@pytest.mark.parametrize(
    ("triples", "fact_results", "expected"),
    [
        ([], [], []),
        ([_context_triple("A", "CAUSES", "B", "導致", "A 導致 B")], [], ["- A 導致 B"]),
        ([], [{"fact_text": "C 需要 D", "subject": "C", "rel_type": "REQUIRES", "object": "D", "verb": "需要"}], ["- C 需要 D"]),
        ([_context_triple("A", "CAUSES", "B", "導致", "A 導致 B")], [{"fact_text": "C 需要 D", "subject": "C", "rel_type": "REQUIRES", "object": "D", "verb": "需要"}], ["- A 導致 B", "- C 需要 D"]),
        ([_context_triple("A", "REL", "B", "一", "A 一 B")], [{"fact_text": "A 二 B", "subject": "A", "rel_type": "REL", "object": "B", "verb": "二"}], ["- A 一 B"]),
    ],
)
def test_merge_fact_lines_is_bfs_then_fact_concatenation(triples, fact_results, expected):
    from services.context import fact_lines

    assert fact_lines.merge_fact_lines(triples, fact_results) == expected
    assert fact_lines.merge_fact_lines(triples, fact_results) == (
        fact_lines.split_fact_lines(triples, fact_results)[0]
        + fact_lines.split_fact_lines(triples, fact_results)[1]
    )
