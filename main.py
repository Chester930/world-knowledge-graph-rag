import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.auth import require_api_key
from core.config import settings
from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from repositories.concept_repo import ConceptRepository
from routers import agent, documents, knowledge_graph, search, staging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    embedding = init_providers()
    await ConceptRepository(get_driver()).create_vector_index(embedding.dim)
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


# 明確加 HEAD：docker-compose healthcheck 用 `wget --spider` 送 HEAD 請求，
# 純 GET route 不會自動接受 HEAD，會回 405 讓 healthcheck 永遠判定 unhealthy。
@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok", "version": "2.0.0-dev"}
