import ast
from pathlib import Path
from uuid import uuid4

import pytest

from models.knowledge_graph import SVOTriple
from models.law_document import LawDocument
from routers import agent


def _triple(
    subject="A",
    rel_type="RELATED_TO",
    object_="B",
    verb="導致",
    natural_text=None,
    source_doc_id=None,
):
    return SVOTriple(
        subject=subject,
        subject_type="概念",
        rel_type=rel_type,
        verb=verb,
        object=object_,
        object_type="概念",
        natural_text=natural_text,
        source_doc_id=source_doc_id,
    )


def test_telemetry_names_reexported_as_same_function_objects():
    from services.context import telemetry

    assert agent._serialize_document is telemetry.serialize_document
    assert agent._build_retrieval_telemetry is telemetry.build_retrieval_telemetry
    assert agent._build_retrieval_trace is telemetry.build_retrieval_trace
    assert agent._serialize_sources is telemetry.serialize_sources


def test_serialize_document_none_is_none():
    from services.context import telemetry

    assert telemetry.serialize_document(None) is None


def test_serialize_document_preserves_field_values_and_key_order():
    from services.context import telemetry

    document = LawDocument(
        kg_id=uuid4(),
        source_doc_id=uuid4(),
        source="s",
        title="標題",
        record_type="law",
        content_hash="h",
        update_date="20251209",
        effective_date=None,
        effective_note="備註",
    )

    serialized = telemetry.serialize_document(document)

    assert serialized == {
        "title": "標題",
        "update_date": "20251209",
        "effective_date": None,
        "effective_note": "備註",
    }
    assert list(serialized) == ["title", "update_date", "effective_date", "effective_note"]


@pytest.mark.parametrize(
    ("triples", "fact_results", "latency_s", "expected"),
    [
        (
            [],
            [],
            0.0,
            {
                "retrieved_char_count": 0,
                "triple_count": 0,
                "fact_count": 0,
                "retrieval_latency_ms": 0.0,
            },
        ),
        (
            [_triple(natural_text="A 導致 B")],
            [{"fact_text": "甲 \n規定 乙"}, {"fact_text": None}, {}],
            0.123,
            {
                "retrieved_char_count": 8,
                "triple_count": 1,
                "fact_count": 3,
                "retrieval_latency_ms": 123.0,
            },
        ),
        (
            [_triple(natural_text=None)],
            [{"fact_text": None}, {"other": "missing fact_text"}],
            1.23456,
            {
                "retrieved_char_count": 0,
                "triple_count": 1,
                "fact_count": 2,
                "retrieval_latency_ms": 1234.6,
            },
        ),
    ],
)
def test_build_retrieval_telemetry_cases(triples, fact_results, latency_s, expected):
    from services.context import telemetry

    assert telemetry.build_retrieval_telemetry(triples, fact_results, latency_s) == expected


def test_build_retrieval_trace_without_prompt_measurement():
    from services.context import telemetry

    document_id = uuid4()
    triples = [_triple(source_doc_id=document_id)]
    fact_results = [
        {
            "fact_text": "甲 規定 乙（概念）",
            "score": 0.91,
            "source_doc_id": str(document_id),
            "source_svo_chunk_index": "3",
            "article_no": "第1條",
        },
        {"fact_text": "丙", "source_doc_id": None, "source_svo_chunk_index": None},
    ]

    trace = telemetry.build_retrieval_trace(triples, fact_results, prompt_lines=None)

    assert trace == {
        "facts": [
            {
                "kind": "fact",
                "rank": 0,
                "text": "甲 規定 乙（概念）",
                "score": 0.91,
                "source_doc_id": str(document_id),
                "source_svo_chunk_index": 3,
                "article_no": "第1條",
                "in_prompt": None,
            },
            {
                "kind": "fact",
                "rank": 1,
                "text": "丙",
                "score": None,
                "source_doc_id": None,
                "source_svo_chunk_index": None,
                "article_no": None,
                "in_prompt": None,
            },
        ],
        "triples": [
            {
                "kind": "triple",
                "rank": 0,
                "text": "A 導致 B",
                "score": None,
                "source_doc_id": str(document_id),
                "source_svo_chunk_index": None,
                "article_no": None,
                "in_prompt": None,
            }
        ],
        "prompt_lines": None,
    }


def test_build_retrieval_trace_marks_rendered_lines_and_preserves_order():
    from services.context import telemetry

    document_id = uuid4()
    triples = [_triple(source_doc_id=document_id, natural_text="A（概念） 導致 B（PERSON）")]
    fact_results = [
        {
            "fact_text": "甲 規定 乙（概念）",
            "score": 0.91,
            "source_doc_id": str(document_id),
            "source_svo_chunk_index": 0,
            "article_no": "第1條",
        },
        {"fact_text": "", "source_doc_id": None, "source_svo_chunk_index": None},
    ]
    prompt_lines = [["- 甲 規定 乙", "- A 導致 B"]]

    trace = telemetry.build_retrieval_trace(triples, fact_results, prompt_lines)

    assert trace["facts"][0]["in_prompt"] is True
    assert trace["facts"][1]["in_prompt"] is False
    assert trace["facts"][0]["rank"] == 0
    assert trace["facts"][1]["rank"] == 1
    assert trace["triples"][0]["text"] == "A（概念） 導致 B（PERSON）"
    assert trace["triples"][0]["in_prompt"] is True
    assert trace["prompt_lines"] == prompt_lines


def test_serialize_sources_empty_preserves_top_level_key_order():
    from services.context import telemetry

    serialized = telemetry.serialize_sources([], [], None, document_map=None)

    assert serialized == {
        "resolved_rel_type": None,
        "retrieval_telemetry": None,
        "retrieval_trace": None,
        "triples": [],
        "facts": [],
    }
    assert list(serialized) == [
        "resolved_rel_type",
        "retrieval_telemetry",
        "retrieval_trace",
        "triples",
        "facts",
    ]


def test_serialize_sources_attaches_document_and_passes_telemetry_trace():
    from services.context import telemetry

    document_id = uuid4()
    triple = _triple(source_doc_id=document_id)
    fact_results = [
        {
            "fact_id": "id",
            "fact_text": "甲 規定 乙",
            "subject": "甲",
            "object": "乙",
            "rel_type": "R",
            "score": 0.8,
            "source_doc_id": str(document_id),
        }
    ]
    document = LawDocument(
        kg_id=uuid4(),
        source_doc_id=document_id,
        source="s",
        title="標題",
        record_type="law",
        content_hash="h",
        update_date="2025",
        effective_date="2026",
        effective_note=None,
    )
    telemetry_value = {"fact_count": 1}
    trace_value = {"facts": []}

    serialized = telemetry.serialize_sources(
        [triple],
        fact_results,
        "R",
        {str(document_id): document},
        telemetry_value,
        trace_value,
    )

    expected_document = {
        "title": "標題",
        "update_date": "2025",
        "effective_date": "2026",
        "effective_note": None,
    }
    assert serialized["retrieval_telemetry"] is telemetry_value
    assert serialized["retrieval_trace"] is trace_value
    assert serialized["triples"][0]["document"] == expected_document
    assert serialized["facts"][0]["document"] == expected_document
    assert list(serialized["triples"][0]) == [
        "subject",
        "subject_type",
        "verb",
        "object",
        "object_type",
        "rel_type",
        "source",
        "source_svo_chunk_file",
        "natural_text",
        "document",
    ]


def test_serialize_sources_missing_document_is_none():
    from services.context import telemetry

    triple = _triple(source_doc_id=uuid4())

    serialized = telemetry.serialize_sources([triple], [], "R", document_map={})

    assert serialized["triples"][0]["document"] is None


def test_telemetry_module_has_no_reverse_dependency():
    from services.context import telemetry

    tree = ast.parse(Path(telemetry.__file__).read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    allowed = {
        "models.knowledge_graph",
        "models.law_document",
        "services.context.fact_lines",
    }
    assert imported_modules <= allowed
    assert not any(module == "routers" or module.startswith("routers.") for module in imported_modules)
    assert not any(module == "repositories" or module.startswith("repositories.") for module in imported_modules)
    assert not any(
        module.startswith("services.") and module != "services.context.fact_lines"
        for module in imported_modules
    )
