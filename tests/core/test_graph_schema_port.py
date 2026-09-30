"""GraphSchemaPort 契約／委派／依賴方向測試（報告164 V1）。"""

import ast
from pathlib import Path
from uuid import uuid4

import pytest

from core.ports.fake_graph_schema import FakeGraphSchema
from core.ports.graph_schema import (
    EmbeddingMeta,
    FulltextIndexSpec,
    FulltextTarget,
    GraphSchemaPort,
    VectorIndexSpec,
    VectorTarget,
)

REPO = Path(__file__).resolve().parents[2]
DRIVER = object()

# 被委派的既有函式：(模組屬性路徑, 事件名稱)
_SVO = {
    "create_entity_index": lambda a, k: ("entity_uniqueness",),
    "create_chunk_vector_index": lambda a, k: ("vector", "chunk_embedding", k.get("dim"), None),
    "create_entity_name_vector_index": lambda a, k: ("vector", "entity_name", k.get("dim"), None),
    "create_fact_vector_index": lambda a, k: ("vector", "fact", k.get("dim"), a[1]),
    "create_sentence_vector_index": lambda a, k: ("vector", "sentence", k.get("dim"), a[1]),
    "create_related_to_vector_index": lambda a, k: ("vector", "related_to_verb", k.get("dim"), None),
    "create_entity_name_fulltext_index": lambda a, k: ("fulltext", "entity_name", None),
    "create_fact_fulltext_index": lambda a, k: ("fulltext", "fact", a[1]),
}


@pytest.fixture(params=["fake", "adapter"])
def impl(request, monkeypatch):
    """回傳 (port, calls)；adapter 以 spy 取代被委派的既有函式並把呼叫正規化成與 fake 相同的事件。"""
    if request.param == "fake":
        fake = FakeGraphSchema()
        return fake, fake.calls

    from core import embedding_guard, vector_migration
    from repositories.concept_repo import ConceptRepository
    from services import svo_service
    from services.graph_store.neo4j_schema import Neo4jGraphSchema

    events: list[tuple] = []
    for name, norm in _SVO.items():
        async def spy(*a, _norm=norm, **k):
            events.append(_norm(a, k))
        monkeypatch.setattr(svo_service, name, spy)

    async def concept_spy(self, **k):
        events.append(("vector", "concept", k.get("dim"), None))
    monkeypatch.setattr(ConceptRepository, "create_vector_index", concept_spy)

    async def migrate_spy(driver, *, obsolete_index_names=(), **k):
        obs = tuple(obsolete_index_names)
        events.append(("migrate", k.get("dim"), obs))
        return list(obs)
    monkeypatch.setattr(vector_migration, "migrate_vector_indexes", migrate_spy)

    async def meta_spy(driver, provider, model_name, dim):
        events.append(("embedding_meta", provider, model_name, dim))
    monkeypatch.setattr(embedding_guard, "check_and_register", meta_spy)
    return Neo4jGraphSchema(DRIVER), events


def test_implements_protocol(impl):
    assert isinstance(impl[0], GraphSchemaPort)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [VectorTarget.CHUNK_EMBEDDING, VectorTarget.ENTITY_NAME, VectorTarget.RELATED_TO_VERB, VectorTarget.CONCEPT])
@pytest.mark.parametrize("dim", [None, 1024])
async def test_vector_index_without_kg(impl, target, dim):
    port, calls = impl
    await port.ensure_vector_index(VectorIndexSpec(target, dim=dim))
    assert calls == [("vector", target.value, dim, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [VectorTarget.FACT, VectorTarget.SENTENCE])
async def test_vector_index_per_kg(impl, target):
    port, calls = impl
    kg = uuid4()
    await port.ensure_vector_index(VectorIndexSpec(target, dim=8, kg_id=kg))
    assert calls == [("vector", target.value, 8, kg)]


@pytest.mark.asyncio
async def test_fulltext_indexes(impl):
    port, calls = impl
    kg = uuid4()
    await port.ensure_fulltext_index(FulltextIndexSpec(FulltextTarget.ENTITY_NAME))
    await port.ensure_fulltext_index(FulltextIndexSpec(FulltextTarget.FACT, kg_id=kg))
    assert calls == [("fulltext", "entity_name", None), ("fulltext", "fact", kg)]


@pytest.mark.asyncio
async def test_entity_uniqueness_and_repeat_calls_are_allowed(impl):
    port, calls = impl
    await port.ensure_entity_uniqueness()
    await port.ensure_entity_uniqueness()
    assert calls == [("entity_uniqueness",)] * 2


@pytest.mark.asyncio
async def test_migrate_returns_removed_names(impl):
    port, calls = impl
    removed = await port.migrate_vector_indexes(dim=16, obsolete_index_names=["old_idx"])
    assert list(removed) == ["old_idx"]
    assert calls == [("migrate", 16, ("old_idx",))]


@pytest.mark.asyncio
async def test_embedding_meta_passes_provider_model_dim(impl):
    port, calls = impl
    await port.check_embedding_meta(EmbeddingMeta("ollama", "bge-m3", 1024))
    assert calls == [("embedding_meta", "ollama", "bge-m3", 1024)]


def test_all_six_existing_vector_targets_are_expressible():
    """故意破壞 (c)：VectorIndexSpec 缺任一現有目標時，此測試與上方參數化契約測試會失敗。"""
    assert {t.value for t in VectorTarget} == {
        "chunk_embedding", "entity_name", "fact", "sentence", "related_to_verb", "concept"}
    assert {t.value for t in FulltextTarget} == {"entity_name", "fact"}


@pytest.mark.parametrize("bad", [
    lambda: VectorIndexSpec(VectorTarget.FACT),
    lambda: VectorIndexSpec(VectorTarget.SENTENCE),
    lambda: VectorIndexSpec(VectorTarget.CHUNK_EMBEDDING, kg_id=uuid4()),
    lambda: VectorIndexSpec(VectorTarget.CONCEPT, dim=0),
    lambda: FulltextIndexSpec(FulltextTarget.FACT),
    lambda: FulltextIndexSpec(FulltextTarget.ENTITY_NAME, kg_id=uuid4()),
])
def test_spec_validation(bad):
    with pytest.raises(ValueError):
        bad()


@pytest.mark.asyncio
async def test_fake_embedding_meta_mismatch_raises():
    fake = FakeGraphSchema()
    await fake.check_embedding_meta(EmbeddingMeta("ollama", "bge-m3", 1024))
    with pytest.raises(RuntimeError):
        await fake.check_embedding_meta(EmbeddingMeta("ollama", "other", 384))


# ── 委派（adapter 專屬）：呼叫同一個既有函式、相同引數 ─────────────────────────


@pytest.mark.asyncio
async def test_adapter_delegates_same_functions_with_same_arguments(monkeypatch):
    from core import embedding_guard, vector_migration
    from repositories.concept_repo import ConceptRepository
    from services import svo_service
    from services.graph_store.neo4j_schema import Neo4jGraphSchema

    seen: list[tuple] = []

    def make(name):
        async def spy(*a, **k):
            seen.append((name, a, tuple(sorted(k.items()))))
        return spy

    for name in list(_SVO):
        monkeypatch.setattr(svo_service, name, make(name))

    async def concept_spy(self, **k):
        seen.append(("ConceptRepository.create_vector_index", (self.driver,), tuple(sorted(k.items()))))
    monkeypatch.setattr(ConceptRepository, "create_vector_index", concept_spy)

    async def migrate(driver, **k):
        seen.append(("migrate_vector_indexes", (driver,), tuple(sorted((a, tuple(b) if a == "obsolete_index_names" else b) for a, b in k.items()))))
        return []
    monkeypatch.setattr(vector_migration, "migrate_vector_indexes", migrate)

    async def meta(*a):
        seen.append(("check_and_register", a, ()))
    monkeypatch.setattr(embedding_guard, "check_and_register", meta)

    port = Neo4jGraphSchema(DRIVER)
    kg = uuid4()
    await port.ensure_entity_uniqueness()
    await port.ensure_vector_index(VectorIndexSpec(VectorTarget.CHUNK_EMBEDDING, dim=3))
    await port.ensure_vector_index(VectorIndexSpec(VectorTarget.ENTITY_NAME))
    await port.ensure_vector_index(VectorIndexSpec(VectorTarget.FACT, dim=4, kg_id=kg))
    await port.ensure_vector_index(VectorIndexSpec(VectorTarget.SENTENCE, kg_id=kg))
    await port.ensure_vector_index(VectorIndexSpec(VectorTarget.RELATED_TO_VERB, dim=5))
    await port.ensure_vector_index(VectorIndexSpec(VectorTarget.CONCEPT, dim=6))
    await port.ensure_fulltext_index(FulltextIndexSpec(FulltextTarget.ENTITY_NAME))
    await port.ensure_fulltext_index(FulltextIndexSpec(FulltextTarget.FACT, kg_id=kg))
    await port.migrate_vector_indexes(dim=7, obsolete_index_names=["x"])
    await port.check_embedding_meta(EmbeddingMeta("p", "m", 9))

    assert seen == [
        ("create_entity_index", (DRIVER,), ()),
        ("create_chunk_vector_index", (DRIVER,), (("dim", 3),)),
        ("create_entity_name_vector_index", (DRIVER,), ()),
        ("create_fact_vector_index", (DRIVER, kg), (("dim", 4),)),
        ("create_sentence_vector_index", (DRIVER, kg), ()),
        ("create_related_to_vector_index", (DRIVER,), (("dim", 5),)),
        ("ConceptRepository.create_vector_index", (DRIVER,), (("dim", 6),)),
        ("create_entity_name_fulltext_index", (DRIVER,), ()),
        ("create_fact_fulltext_index", (DRIVER, kg), ()),
        ("migrate_vector_indexes", (DRIVER,), (("dim", 7), ("obsolete_index_names", ("x",)))),
        ("check_and_register", (DRIVER, "p", "m", 9), ()),
    ]


# ── 依賴方向 AST ─────────────────────────────────────────────────────────


def _imports(path: Path) -> list[str]:
    out = []
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
            out += [f"{n.module}.{a.name}" for a in n.names]
    return out


def test_core_ports_only_depends_on_stdlib():
    forbidden = ("services", "repositories", "routers", "models", "neo4j")
    for f in (REPO / "core" / "ports").glob("*.py"):
        for m in _imports(f):
            assert m.split(".")[0] not in forbidden, (f.name, m)
            assert not m.startswith("core.") or m.startswith("core.ports"), (f.name, m)


def test_graph_store_is_not_imported_by_any_production_module():
    skip = {"tests", "worktrees", ".git", ".claude", "node_modules", "__pycache__"}
    graph_store = REPO / "services" / "graph_store"
    offenders = []
    for f in REPO.rglob("*.py"):
        rel = f.relative_to(REPO)
        if skip & set(rel.parts) or graph_store in f.parents:
            continue
        if any(m == "services.graph_store" or m.startswith("services.graph_store.") for m in _imports(f)):
            offenders.append(str(rel))
        # from services import graph_store
    assert not offenders, offenders
