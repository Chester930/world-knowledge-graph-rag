from pathlib import Path
from uuid import uuid4

import pytest

from core import config
from models.knowledge_graph import KnowledgeGraphCreate, KnowledgeGraphUpdate
from repositories.kg_repo import KGRepository


class FakeResult:
    def __init__(self, records=None):
        self.records = records or []


class FakeKGDriver:
    """模擬 `KnowledgeGraph` 節點的 CRUD，供 `KGRepository` 測試使用——
    以字典模擬 Neo4j 節點儲存，依查詢字串形狀判斷要執行的操作。"""

    def __init__(self):
        self._nodes: dict[str, dict] = {}

    async def execute_query(self, query: str, **params):
        stripped = query.strip()
        if stripped.startswith("CREATE (k:KnowledgeGraph {"):
            node = {
                "id": params["id"],
                "name": params["name"],
                "description": params["description"],
                "folder_path": params["folder_path"],
                "is_public": params["is_public"],
                "db_name": "",
                "doc_count": 0,
                "entity_count": 0,
                "relation_count": 0,
                "created_at": params["now"],
                "updated_at": params["now"],
            }
            self._nodes[params["id"]] = node
            return FakeResult()
        if stripped == "MATCH (k:KnowledgeGraph {id: $id}) RETURN k":
            node = self._nodes.get(params["id"])
            return FakeResult([{"k": dict(node)}] if node else [])
        if stripped == "MATCH (k:KnowledgeGraph) RETURN k":
            return FakeResult([{"k": dict(n)} for n in self._nodes.values()])
        if stripped.startswith("MATCH (k:KnowledgeGraph {id: $id}) SET"):
            node = self._nodes.get(params["id"])
            if node is None:
                return FakeResult()
            for key, value in params.items():
                if key != "id":
                    node[key] = value
            return FakeResult([{"k": dict(node)}])
        if stripped == "MATCH (k:KnowledgeGraph {id: $id}) DELETE k":
            self._nodes.pop(params["id"], None)
            return FakeResult()
        raise AssertionError(f"未預期的查詢：{stripped}")


@pytest.mark.asyncio
async def test_create_persists_node_and_builds_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())

    kg = await repo.create(KnowledgeGraphCreate(name="測試 KG", description="描述"))

    assert kg.name == "測試 KG"
    assert kg.description == "描述"
    assert kg.db_name == ""
    assert kg.doc_count == 0
    assert Path(kg.folder_path).exists()
    assert Path(kg.folder_path).name == str(kg.id)


@pytest.mark.asyncio
async def test_get_returns_none_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())

    assert await repo.get(uuid4()) is None


@pytest.mark.asyncio
async def test_get_returns_created_kg(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())
    created = await repo.create(KnowledgeGraphCreate(name="KG-A"))

    fetched = await repo.get(created.id)

    assert fetched == created


@pytest.mark.asyncio
async def test_list_all_returns_empty_list_when_no_kg(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())

    assert await repo.list_all() == []


@pytest.mark.asyncio
async def test_list_all_returns_every_created_kg(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    driver = FakeKGDriver()
    repo = KGRepository(driver)
    await repo.create(KnowledgeGraphCreate(name="KG-A"))
    await repo.create(KnowledgeGraphCreate(name="KG-B"))

    kgs = await repo.list_all()

    assert {kg.name for kg in kgs} == {"KG-A", "KG-B"}


@pytest.mark.asyncio
async def test_update_only_changes_provided_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())
    created = await repo.create(KnowledgeGraphCreate(name="舊名稱", description="舊描述"))

    updated = await repo.update(created.id, KnowledgeGraphUpdate(name="新名稱"))

    assert updated.name == "新名稱"
    assert updated.description == "舊描述"  # 未帶入 patch 的欄位不變
    assert updated.updated_at >= created.updated_at


@pytest.mark.asyncio
async def test_update_raises_when_kg_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())

    with pytest.raises(ValueError):
        await repo.update(uuid4(), KnowledgeGraphUpdate(name="不存在"))


@pytest.mark.asyncio
async def test_delete_removes_node(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())
    created = await repo.create(KnowledgeGraphCreate(name="待刪除"))

    await repo.delete(created.id)

    assert await repo.get(created.id) is None


@pytest.mark.asyncio
async def test_delete_is_noop_when_kg_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())

    await repo.delete(uuid4())  # 不應拋出例外


@pytest.mark.asyncio
async def test_delete_does_not_remove_local_folder(tmp_path, monkeypatch):
    """資料夾內容屬使用者資料，delete() 不應自動刪檔（見 docstring 誠實聲明）。"""
    monkeypatch.setattr(config.settings, "workspace_dir", str(tmp_path))
    repo = KGRepository(FakeKGDriver())
    created = await repo.create(KnowledgeGraphCreate(name="保留資料夾"))

    await repo.delete(created.id)

    assert Path(created.folder_path).exists()
