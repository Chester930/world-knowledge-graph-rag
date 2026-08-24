from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from neo4j import AsyncDriver

from core.config import settings
from core.database import drop_kg_database
from models.knowledge_graph import KnowledgeGraph, KnowledgeGraphCreate, KnowledgeGraphUpdate


class KGRepository:
    """`KnowledgeGraph` 節點 CRUD（主資料庫）。

    對應 `docs/報告/11_抽取管線完整實作任務書.md` P0-1。`db_name` 空白
    （`create()` 預設留空）代表沿用主資料庫——比照本專案既有慣例（所有
    節點/邊皆以 `kg_id` 屬性區隔，非依賴 Neo4j Enterprise 的多資料庫功能，
    見 `core/database.py`「多資料庫管理」註解：Community 版本無法使用），
    `create()` 因此不會自動呼叫 `create_kg_database()`，是否啟用 KG 專用
    資料庫留給呼叫端另外決定，非本次範圍。
    """

    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def create(self, kg: KnowledgeGraphCreate) -> KnowledgeGraph:
        """建立 `KnowledgeGraph` 節點，並在 `settings.workspace_dir` 底下建立
        對應的本地資料夾（`folder_path`，以 KG id 命名，比照
        `core/config.py::staging_folder()` 同一慣例）。"""
        kg_id = uuid4()
        now = datetime.now(timezone.utc)
        folder_path = Path(settings.workspace_dir) / str(kg_id)
        folder_path.mkdir(parents=True, exist_ok=True)

        await self.driver.execute_query(
            """
            CREATE (k:KnowledgeGraph {
                id: $id, name: $name, description: $description,
                folder_path: $folder_path, is_public: $is_public, db_name: '',
                doc_count: 0, entity_count: 0, relation_count: 0,
                pronoun_lexicon_exclude: [],
                created_at: $now, updated_at: $now
            })
            """,
            id=str(kg_id),
            name=kg.name,
            description=kg.description,
            folder_path=str(folder_path),
            is_public=kg.is_public,
            now=now.isoformat(),
        )
        return KnowledgeGraph(
            id=kg_id,
            name=kg.name,
            description=kg.description,
            folder_path=str(folder_path),
            is_public=kg.is_public,
            db_name="",
            doc_count=0,
            entity_count=0,
            relation_count=0,
            pronoun_lexicon_exclude=[],
            created_at=now,
            updated_at=now,
        )

    async def get(self, kg_id: UUID) -> KnowledgeGraph | None:
        """查無資料回傳 `None`，不拋例外（呼叫端 `routers/staging.py` 已依此
        慣例撰寫 `if kg is None`）。"""
        result = await self.driver.execute_query(
            "MATCH (k:KnowledgeGraph {id: $id}) RETURN k",
            id=str(kg_id),
        )
        if not result.records:
            return None
        return _record_to_model(result.records[0]["k"])

    async def list_all(self) -> list[KnowledgeGraph]:
        """查無資料回傳空清單，不拋例外（`main.py::_restart_task_queue()`
        已依此慣例處理）。"""
        result = await self.driver.execute_query("MATCH (k:KnowledgeGraph) RETURN k")
        return [_record_to_model(r["k"]) for r in result.records]

    async def update(self, kg_id: UUID, patch: KnowledgeGraphUpdate) -> KnowledgeGraph:
        """只更新 `patch` 內實際帶值（非預設 `None`）的欄位。"""
        updates = patch.model_dump(exclude_unset=True, exclude_none=True)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"k.{key} = ${key}" for key in updates)

        result = await self.driver.execute_query(
            f"MATCH (k:KnowledgeGraph {{id: $id}}) SET {set_clause} RETURN k",
            id=str(kg_id),
            **updates,
        )
        if not result.records:
            raise ValueError(f"找不到 KG：{kg_id}")
        return _record_to_model(result.records[0]["k"])

    async def delete(self, kg_id: UUID) -> None:
        """刪除 `KnowledgeGraph` 節點；若該 KG 有專用資料庫（`db_name` 非空），
        一併呼叫 `drop_kg_database()`。**不刪除本地資料夾**——資料夾內容屬
        使用者資料，比照本專案「危險操作需人工確認」慣例，清除交給呼叫端
        或使用者手動處理，不由程式自動刪檔。"""
        kg = await self.get(kg_id)
        if kg is None:
            return
        await self.driver.execute_query(
            "MATCH (k:KnowledgeGraph {id: $id}) DELETE k",
            id=str(kg_id),
        )
        if kg.db_name:
            await drop_kg_database(kg.db_name)


def _record_to_model(node) -> KnowledgeGraph:
    data = dict(node)
    return KnowledgeGraph(
        id=UUID(data["id"]),
        name=data["name"],
        description=data["description"],
        folder_path=data["folder_path"],
        is_public=data["is_public"],
        db_name=data.get("db_name", ""),
        doc_count=data.get("doc_count", 0),
        entity_count=data.get("entity_count", 0),
        relation_count=data.get("relation_count", 0),
        pronoun_lexicon_exclude=data.get("pronoun_lexicon_exclude", []),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )
