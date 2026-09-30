import ast
from pathlib import Path
from uuid import UUID

from models.knowledge_graph import SVOTriple
from routers import agent


DOC_A = UUID("00000000-0000-0000-0000-00000000000a")
DOC_B = UUID("00000000-0000-0000-0000-00000000000b")
DOC_C = UUID("00000000-0000-0000-0000-00000000000c")


def _triple(source_doc_id=None, rel_type="RELATED_TO"):
    return SVOTriple(
        subject="主詞",
        verb="導致",
        object="受詞",
        rel_type=rel_type,
        source_doc_id=source_doc_id,
    )


def test_scope_names_reexported_as_same_function_objects():
    from services.retrieval import scope

    assert agent._relevant_doc_ids_from_facts is scope.relevant_doc_ids_from_facts
    assert agent._intersect_doc_scopes is scope.intersect_doc_scopes
    assert agent._resolve_doc_scope is scope.resolve_doc_scope
    assert agent._scope_by_source_doc_ids is scope.scope_by_source_doc_ids
    assert agent._filter_triples_by_source_doc_ids is scope.filter_triples_by_source_doc_ids
    assert agent._filter_facts_by_source_doc_ids is scope.filter_facts_by_source_doc_ids
    assert agent._filter_triples_by_relation_type is scope.filter_triples_by_relation_type

    assert hasattr(agent, "_relevant_doc_ids_from_seeds")
    assert hasattr(agent, "_find_seed_entities")
    assert hasattr(agent, "_DOC_SCOPE_TOP_N_FACTS")
    assert agent._DOC_SCOPE_TOP_N_FACTS == 5


def test_relevant_doc_ids_from_facts_cases():
    from services.retrieval import scope

    facts = [
        {"source_doc_id": DOC_A},
        {"source_doc_id": str(DOC_A)},
        {"source_doc_id": "not-a-uuid"},
        {"source_doc_id": None},
        {"source_doc_id": ""},
        {},
        {"source_doc_id": DOC_B},
    ]
    assert scope.relevant_doc_ids_from_facts(facts) == {DOC_A, DOC_B}
    assert scope.relevant_doc_ids_from_facts(facts, top_n=None) == {DOC_A, DOC_B}
    assert scope.relevant_doc_ids_from_facts(facts, top_n=0) == set()
    assert scope.relevant_doc_ids_from_facts(facts, top_n=1) == {DOC_A}
    assert scope.relevant_doc_ids_from_facts(facts, top_n=100) == {DOC_A, DOC_B}
    assert scope.relevant_doc_ids_from_facts([]) == set()


def test_intersect_and_resolve_doc_scope_cases():
    from services.retrieval import scope

    assert scope.intersect_doc_scopes({DOC_A, DOC_B}, None) == {DOC_A, DOC_B}
    assert scope.intersect_doc_scopes({DOC_A, DOC_B}, []) == {DOC_A, DOC_B}
    assert scope.intersect_doc_scopes(set(), [DOC_B, DOC_C]) == {DOC_B, DOC_C}
    assert scope.intersect_doc_scopes({DOC_A, DOC_B}, [DOC_B, DOC_C]) == {DOC_B}
    assert scope.intersect_doc_scopes({DOC_A}, [DOC_B, DOC_C]) == {DOC_B, DOC_C}

    assert scope.resolve_doc_scope({DOC_A}, {DOC_B}, None) == {DOC_A}
    assert scope.resolve_doc_scope(set(), {DOC_A, DOC_B}, None) == {DOC_A, DOC_B}
    assert scope.resolve_doc_scope(set(), set(), None) == set()
    assert scope.resolve_doc_scope({DOC_A, DOC_B}, set(), [DOC_B, DOC_C]) == {DOC_B}
    assert scope.resolve_doc_scope(set(), set(), [DOC_C]) == {DOC_C}


def test_scope_by_source_doc_ids_cases():
    from services.retrieval import scope

    items = [
        {"source_doc_id": DOC_A, "name": "in"},
        {"source_doc_id": None, "name": "unknown"},
        {"source_doc_id": DOC_B, "name": "out"},
    ]
    unchanged = scope.scope_by_source_doc_ids(items, set(), lambda item: item.get("source_doc_id"))
    assert unchanged is items
    assert scope.scope_by_source_doc_ids(items, {DOC_A}, lambda item: item.get("source_doc_id")) == [
        items[0], items[1]
    ]

    all_out = [{"source_doc_id": DOC_B}]
    assert scope.scope_by_source_doc_ids(all_out, {DOC_A}, lambda item: item.get("source_doc_id")) is all_out
    assert scope.scope_by_source_doc_ids([], {DOC_A}, lambda item: item.get("source_doc_id")) == []


def test_filter_triples_and_facts_by_source_doc_ids_cases():
    from services.retrieval import scope

    triples = [_triple(DOC_A), _triple(None), _triple(DOC_B)]
    filtered_triples = scope.filter_triples_by_source_doc_ids(triples, {DOC_A})
    assert filtered_triples == [triples[0], triples[1]]

    triples_all_out = [_triple(DOC_B)]
    assert scope.filter_triples_by_source_doc_ids(triples_all_out, {DOC_A}) is triples_all_out

    facts = [
        {"source_doc_id": DOC_A, "id": "uuid"},
        {"source_doc_id": str(DOC_A), "id": "string"},
        {"source_doc_id": "invalid", "id": "invalid"},
        {"source_doc_id": None, "id": "none"},
        {"id": "missing"},
        {"source_doc_id": DOC_B, "id": "out"},
    ]
    filtered_facts = scope.filter_facts_by_source_doc_ids(facts, {DOC_A})
    assert filtered_facts == facts[:5]

    facts_all_out = [{"source_doc_id": str(DOC_B)}]
    assert scope.filter_facts_by_source_doc_ids(facts_all_out, {DOC_A}) is facts_all_out
    assert scope.filter_facts_by_source_doc_ids(facts, set()) is facts


def test_filter_triples_by_relation_type_cases():
    from services.retrieval import scope

    triples = [_triple(DOC_A, "CAUSES"), _triple(DOC_B, "RELATED_TO")]
    assert scope.filter_triples_by_relation_type(triples, None) is triples
    assert scope.filter_triples_by_relation_type(triples, "CAUSES") == [triples[0]]
    assert scope.filter_triples_by_relation_type(triples, "MISSING") == []
    assert scope.filter_triples_by_relation_type([], "CAUSES") == []


def test_scope_module_has_no_reverse_dependency():
    from services.retrieval import scope

    tree = ast.parse(Path(scope.__file__).read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    allowed = {"__future__", "uuid", "models.knowledge_graph"}
    assert imported_modules <= allowed
    assert not any(module == "routers" or module.startswith("routers.") for module in imported_modules)
    assert not any(module == "repositories" or module.startswith("repositories.") for module in imported_modules)
    assert not any(module.startswith("core") for module in imported_modules)
    assert not any(module.startswith("services.") for module in imported_modules)
