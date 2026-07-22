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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def _restart_task_queue() -> None:
    """§ 3.1.2 `RESTART` 進入點：程式重啟時檢查 `task_queue.db` 索引是否
    可信，可信則重置卡住的 `processing`（中斷處理），否則掃描各 KG 資料夾
    記錄檔重建索引（`REBUILD`）。

    `KGRepository` 目前為 stub（見 `repositories/kg_repo.py`），`list_all()`
    會拋出 `NotImplementedError`——此時退化為以空的 KG 資料夾清單呼叫
    `ensure_ready()`（`REBUILD` 分支不會找到任何 KG、不會登記任何 pending
    chunk，但不會讓整個 app 啟動失敗），待 `KGRepository` 實作完成後這裡不需
    要再修改，自然會拿到真正的 KG 清單。
    """
    try:
        kgs = await KGRepository(get_driver()).list_all()
        kg_folders = {str(kg.id): Path(kg.folder_path) for kg in kgs}
    except NotImplementedError:
        logger.warning("KGRepository 尚未實作，task_queue.db 啟動檢查暫時以空 KG 清單執行")
        kg_folders = {}

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
    await _restart_task_queue()
    logger.info(
        f"World Knowledge Graph RAG API 啟動完成 "
        f"[LLM={settings.llm_provider}, Embedding={settings.embedding_provider}]"
    )
    yield
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
