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

from core.auth import require_api_key
from core.config import settings, task_queue_db_path
from core.database import connect, disconnect, get_driver
from core.embedding_guard import check_and_register as check_embedding_consistency
from core.providers.factory import init_providers
from repositories.concept_repo import ConceptRepository
from repositories.kg_repo import KGRepository
from routers import agent, documents, knowledge_graph, search, staging
from services import svo_service, task_queue_service
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
    """
    kgs = await KGRepository(get_driver()).list_all()
    kg_folders = {str(kg.id): Path(kg.folder_path) for kg in kgs}

    task_queue_service.ensure_ready(task_queue_db_path(), kg_folders)


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
    await _restart_task_queue()
    # § 3.1.2「WORKER 執行模型定案」：常駐背景 asyncio 任務，隨宿主行程啟動，
    # 消費 task_queue_service.next_pending()（見 services/extraction_worker.py）。
    app.state.extraction_worker_task = asyncio.create_task(run_extraction_worker(get_driver()))
    logger.info(
        f"World Knowledge Graph RAG API 啟動完成 "
        f"[LLM={settings.llm_provider}, Embedding={settings.embedding_provider}]"
    )
    yield
    app.state.extraction_worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.extraction_worker_task
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
