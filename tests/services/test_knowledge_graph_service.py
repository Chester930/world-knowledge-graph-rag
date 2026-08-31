import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from models.knowledge_graph import KnowledgeGraph, KnowledgeGraphCreate
from services import document_record_service, knowledge_graph_service as svc


def _make_kg(folder_path: str) -> KnowledgeGraph:
    now = datetime.now(timezone.utc)
    return KnowledgeGraph(
        id=uuid4(),
        name="測試 KG",
        description="",
        folder_path=folder_path,
        is_public=True,
        created_at=now,
        updated_at=now,
    )


def _patch_kg_repo(monkeypatch, kg: KnowledgeGraph | None):
    """`build_graph`／`delete_kg`／`create_kg` 只需要驗證自身的協調邏輯（是否
    正確委派給 `KGRepository`、doc_ids 解析、force_rebuild 分支），`KGRepository`
    本身的 Cypher 行為已由 tests/repositories/test_kg_repo.py 覆蓋，這裡改用
    替身類別隔離測試範圍。"""
    class FakeRepo:
        def __init__(self, driver):
            self.driver = driver

        async def get(self, kg_id):
            return kg if (kg is not None and kg_id == kg.id) else None

    monkeypatch.setattr("services.knowledge_graph_service.KGRepository", FakeRepo)


class SpyDriver:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, **params):
        self.calls.append((query.strip(), params))
        return None


@pytest.mark.asyncio
async def test_create_kg_delegates_to_kg_repository(monkeypatch):
    recorded = {}

    class FakeRepo:
        def __init__(self, driver):
            recorded["driver"] = driver

        async def create(self, payload):
            recorded["payload"] = payload
            return "sentinel-kg"

    monkeypatch.setattr("services.knowledge_graph_service.KGRepository", FakeRepo)
    driver = SpyDriver()
    payload = KnowledgeGraphCreate(name="新 KG")

    result = await svc.create_kg(driver, payload)

    assert result == "sentinel-kg"
    assert recorded["driver"] is driver
    assert recorded["payload"] is payload


@pytest.mark.asyncio
async def test_delete_kg_delegates_to_kg_repository(monkeypatch):
    recorded = {}

    class FakeRepo:
        def __init__(self, driver):
            recorded["driver"] = driver

        async def delete(self, kg_id):
            recorded["kg_id"] = kg_id

    monkeypatch.setattr("services.knowledge_graph_service.KGRepository", FakeRepo)
    driver = SpyDriver()
    kg_id = uuid4()

    await svc.delete_kg(driver, kg_id)

    assert recorded["driver"] is driver
    assert recorded["kg_id"] == kg_id


@pytest.mark.asyncio
async def test_build_graph_raises_when_kg_not_found(monkeypatch):
    _patch_kg_repo(monkeypatch, None)

    with pytest.raises(ValueError):
        await svc.build_graph(SpyDriver(), uuid4())


@pytest.mark.asyncio
async def test_build_graph_without_doc_ids_targets_all_document_folders(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_a = kg_folder / "a.md"
    doc_a.mkdir()
    document_record_service.init_record(doc_a, source="a.md", total_chunks=1)
    doc_b = kg_folder / "b.md"
    doc_b.mkdir()
    document_record_service.init_record(doc_b, source="b.md", total_chunks=1)

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)

    triggered = []

    async def _fake_trigger(driver, doc_folder, kg_id):
        triggered.append(doc_folder)

    monkeypatch.setattr("services.knowledge_graph_service.svo_service.trigger_extraction", _fake_trigger)

    await svc.build_graph(SpyDriver(), kg.id)

    assert set(triggered) == {doc_a, doc_b}


@pytest.mark.asyncio
async def test_build_graph_with_doc_ids_only_targets_specified_folders(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_a = kg_folder / "a.md"
    doc_a.mkdir()
    document_record_service.init_record(doc_a, source="a.md", total_chunks=1)
    doc_b = kg_folder / "b.md"
    doc_b.mkdir()
    document_record_service.init_record(doc_b, source="b.md", total_chunks=1)

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)

    triggered = []

    async def _fake_trigger(driver, doc_folder, kg_id):
        triggered.append(doc_folder)

    monkeypatch.setattr("services.knowledge_graph_service.svo_service.trigger_extraction", _fake_trigger)

    await svc.build_graph(SpyDriver(), kg.id, doc_ids=["a.md", "missing.md"])

    assert triggered == [doc_a]


@pytest.mark.asyncio
async def test_build_graph_force_rebuild_without_doc_ids_wipes_kg_content(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)
    monkeypatch.setattr(
        "services.knowledge_graph_service.svo_service.trigger_extraction",
        lambda *a, **k: _noop(),
    )

    driver = SpyDriver()
    await svc.build_graph(driver, kg.id, force_rebuild=True)

    wipe_calls = [c for c in driver.calls if c[0] == "MATCH (n {kg_id: $kg_id}) DETACH DELETE n"]
    assert len(wipe_calls) == 1
    assert wipe_calls[0][1] == {"kg_id": str(kg.id)}


@pytest.mark.asyncio
async def test_build_graph_force_rebuild_refuses_when_article_structure_would_be_lost(tmp_path, monkeypatch):
    """2026-08-31（見 docs/報告/21_抽取管線稽核與修正報告.md）：
    `build_graph(force_rebuild=True)` 不傳 `articles=`，若目標文件先前是用
    `ArticleAwareChunking` 抽取（`article_no` 有值），改用一般切塊會靜默
    覆寫掉 `svo_index.json`、條文邊界全部消失——應直接拋出
    `ArticleStructureLossError`，且不能先執行任何破壞性動作（DETACH DELETE／
    重設進度）。"""
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_a = kg_folder / "a.md"
    doc_a.mkdir()
    document_record_service.init_record(doc_a, source="a.md", total_chunks=1)
    (doc_a / "svo_index.json").write_text(
        json.dumps({"source": "a.md", "chunks": [{"index": 1, "article_no": "第 1 條", "text": "內文"}]}),
        encoding="utf-8",
    )

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)
    monkeypatch.setattr(
        "services.knowledge_graph_service.svo_service.trigger_extraction",
        lambda *a, **k: _noop(),
    )
    reset_calls: list = []
    monkeypatch.setattr(
        "services.knowledge_graph_service.document_record_service.reset_extraction_progress",
        lambda folder: reset_calls.append(folder),
    )

    driver = SpyDriver()
    with pytest.raises(svc.ArticleStructureLossError):
        await svc.build_graph(driver, kg.id, force_rebuild=True)

    assert driver.calls == []  # 沒有任何破壞性 Cypher 被執行
    assert reset_calls == []  # 沒有任何文件的抽取進度被重設


@pytest.mark.asyncio
async def test_build_graph_force_rebuild_with_doc_ids_does_not_wipe_kg_content(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_a = kg_folder / "a.md"
    doc_a.mkdir()
    document_record_service.init_record(doc_a, source="a.md", total_chunks=1)

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)
    monkeypatch.setattr(
        "services.knowledge_graph_service.svo_service.trigger_extraction",
        lambda *a, **k: _noop(),
    )

    driver = SpyDriver()
    await svc.build_graph(driver, kg.id, doc_ids=["a.md"], force_rebuild=True)

    assert driver.calls == []


@pytest.mark.asyncio
async def test_build_graph_force_rebuild_resets_extraction_progress(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    doc_a = kg_folder / "a.md"
    doc_a.mkdir()
    document_record_service.init_record(doc_a, source="a.md", total_chunks=1)
    record = document_record_service.read_record(doc_a)
    record.extraction_status = "completed"
    record.chunk_progress = 1
    record.completed_chunk_indices = [1]
    document_record_service._write_record(doc_a, record)

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)
    monkeypatch.setattr(
        "services.knowledge_graph_service.svo_service.trigger_extraction",
        lambda *a, **k: _noop(),
    )

    await svc.build_graph(SpyDriver(), kg.id, force_rebuild=True)

    reset = document_record_service.read_record(doc_a)
    assert reset.extraction_status == "pending"
    assert reset.chunk_progress == 0
    assert reset.completed_chunk_indices == []


@pytest.mark.asyncio
async def test_build_graph_without_force_rebuild_skips_completed_documents(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    done_folder = kg_folder / "done.md"
    done_folder.mkdir()
    document_record_service.init_record(done_folder, source="done.md", total_chunks=1)
    record = document_record_service.read_record(done_folder)
    record.extraction_status = "completed"
    document_record_service._write_record(done_folder, record)

    pending_folder = kg_folder / "pending.md"
    pending_folder.mkdir()
    document_record_service.init_record(pending_folder, source="pending.md", total_chunks=1)

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)

    triggered = []

    async def _fake_trigger(driver, doc_folder, kg_id):
        triggered.append(doc_folder)

    monkeypatch.setattr("services.knowledge_graph_service.svo_service.trigger_extraction", _fake_trigger)

    await svc.build_graph(SpyDriver(), kg.id, force_rebuild=False)

    assert triggered == [pending_folder]


@pytest.mark.asyncio
async def test_build_graph_skips_folders_without_record(tmp_path, monkeypatch):
    kg_folder = tmp_path / "kg-1"
    kg_folder.mkdir()
    orphan_folder = kg_folder / "orphan"
    orphan_folder.mkdir()  # 沒有 _record.json

    kg = _make_kg(str(kg_folder))
    _patch_kg_repo(monkeypatch, kg)

    triggered = []

    async def _fake_trigger(driver, doc_folder, kg_id):
        triggered.append(doc_folder)

    monkeypatch.setattr("services.knowledge_graph_service.svo_service.trigger_extraction", _fake_trigger)

    await svc.build_graph(SpyDriver(), kg.id)  # 不應拋出例外

    assert triggered == []


async def _noop():
    return None
