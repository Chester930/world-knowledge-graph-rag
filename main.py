import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pathlib import Path
from uuid import UUID

from core.auth import require_api_key
from core.config import settings, task_queue_db_path
from core.database import connect, disconnect, get_driver
from core.embedding_guard import check_and_register as check_embedding_consistency
from core.providers.factory import init_providers
from repositories.concept_repo import ConceptRepository
from repositories.kg_repo import KGRepository
from routers import agent, documents, expand, knowledge_graph, search, staging
from services import document_record_service, svo_service, task_queue_service
from services.expand_worker import run_governance_worker
from services.extraction_worker import run_extraction_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def _restart_task_queue() -> None:
    """§ 3.1.2 `RESTART` 進入點：程式重啟時檢查 `task_queue.db` 索引是否
    可信，可信則重置卡住的 `processing`（中斷處理），否則掃描各 KG 資料夾
    記錄檔重建索引（`REBUILD`）。

    ✅ **2026-08-31 新增（見 `docs/報告/21_抽取管線稽核與修正報告.md`）**：
    對每個被重置的 chunk 呼叫 `revoke_chunk_facts()` 清理 Neo4j 裡可能殘留
    的部分寫入——`merge_triples_to_graph()` 對每筆三元組各自即時 `await`，
    非整個 chunk 一筆交易，若上次執行中斷於某個 chunk 處理到一半，重新
    處理前不清理會導致 Fact 節點重複、citations 重複累加（`ensure_ready()`
    docstring；此為稽核發現的真實風險，非既有已知限制）。`REBUILD` 分支
    （索引本身遺失/損毀）回傳空清單，此路徑的殘留清理暫不在本次範圍。
    """
    kgs = await KGRepository(get_driver()).list_all()
    kg_folders = {str(kg.id): Path(kg.folder_path) for kg in kgs}

    reset_chunks = task_queue_service.ensure_ready(task_queue_db_path(), kg_folders)
    for kg_id_str, source, chunk_index in reset_chunks:
        source_doc_id = str(document_record_service.document_uuid(source))
        stats = await svo_service.revoke_chunk_facts(
            get_driver(), UUID(kg_id_str), source_doc_id, chunk_index,
        )
        logger.info(
            "[Restart] 清理中斷殘留 kg_id=%s source=%s chunk_index=%s -> %s",
            kg_id_str, source, chunk_index, stats,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    embedding = init_providers()
    await check_embedding_consistency(
        get_driver(), settings.embedding_provider, embedding.model_name, embedding.dim
    )
    await ConceptRepository(get_driver()).create_vector_index(embedding.dim)
    await svo_service.create_entity_index(get_driver())
    await svo_service.create_chunk_vector_index(get_driver(), embedding.dim)
    await svo_service.create_related_to_vector_index(get_driver(), embedding.dim)
    # § 3.1.4 §a Fact 向量索引改為 2026-08-19 起每個 KG 各自一個獨立索引
    # （見 svo_service.create_fact_vector_index() docstring），啟動時尚不
    # 知道有哪些 KG，改由 vector_search_facts() 在查詢當下惰性建立
    # （Neo4j 索引本來就會涵蓋建立之前已寫入的節點，不需要預先建立）。
    await _restart_task_queue()
    # § 3.1.2「WORKER 執行模型定案」：常駐背景 asyncio 任務，隨宿主行程啟動，
    # 消費 task_queue_service.next_pending()（見 services/extraction_worker.py）。
    app.state.extraction_worker_task = asyncio.create_task(run_extraction_worker(get_driver()))
    # § 3.1.3 §a「治理 Worker 的實際排程機制」：同一宿主行程內第二個獨立
    # 背景任務，寬鬆迴圈巡視各 KG 候選池（見 services/expand_worker.py）。
    app.state.governance_worker_task = asyncio.create_task(run_governance_worker(get_driver()))
    logger.info(
        f"World Knowledge Graph RAG API 啟動完成 "
        f"[LLM={settings.llm_provider}, Embedding={settings.embedding_provider}]"
    )
    yield
    app.state.extraction_worker_task.cancel()
    app.state.governance_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.extraction_worker_task
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.governance_worker_task
    await disconnect()


app = FastAPI(
    title="World Knowledge Graph RAG",
    description="多場景知識圖譜 RAG 系統",
    version="2.0.0-dev",
    lifespan=lifespan,
)

_protected = [Depends(require_api_key)]

app.include_router(documents.router, dependencies=_protected)
app.include_router(search.router, dependencies=_protected)
app.include_router(agent.router, dependencies=_protected)
app.include_router(knowledge_graph.router, dependencies=_protected)
app.include_router(staging.router, dependencies=_protected)
app.include_router(expand.router, dependencies=_protected)

app.mount("/static", StaticFiles(directory="ui/static"), name="static")
templates = Jinja2Templates(directory="ui/templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/parser-debug", response_class=HTMLResponse)
async def parser_debug(request: Request):
    return templates.TemplateResponse(request, "parser_debug.html")


# 明確加 HEAD：docker-compose healthcheck 用 `wget --spider` 送 HEAD 請求，
# 純 GET route 不會自動接受 HEAD，會回 405 讓 healthcheck 永遠判定 unhealthy。
@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok", "version": "2.0.0-dev"}
