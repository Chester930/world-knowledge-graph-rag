from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Neo4j ──────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── Provider 選擇 ──────────────────────────────────────────────────────────
    llm_provider: str = "ollama"        # ollama | openai | anthropic | gemini | grok
    embedding_provider: str = "local"   # local | openai | ollama

    # ── Ollama（本地）─────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen2.5:7b"
    ollama_embedding_model: str = "nomic-embed-text"

    # ── 本地 Embedding（sentence-transformers）────────────────────────────────
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # ── OpenAI ─────────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_llm_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Anthropic ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # ── Google Gemini ──────────────────────────────────────────────────────────
    google_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # ── xAI Grok ───────────────────────────────────────────────────────────────
    grok_api_key: str = ""
    grok_model: str = "grok-2"

    # ── 系統行為 ───────────────────────────────────────────────────────────────
    concept_extraction_max: int = 8
    score_threshold: float = 0.70
    workspace_dir: str = "./workspace"
    chunk_store_dir: str = "./chunk_store"

    # ── 安全性 ────────────────────────────────────────────────────────────────
    api_key: str = ""     # 設定後，管理端點需帶 X-API-Key header；留空 = 不驗證（僅建議本機開發環境使用）
    max_upload_size_mb: int = 50

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def staging_folder() -> Path:
    """暫存區（未分配文件池）根目錄，對應 docs/論文/03_系統設計與方法論.md § 3.1.1
    的「未分配資料夾池」。集中定義於此，避免 routers/documents.py（文件上傳/解析）
    與 routers/staging.py（暫存區分類/分群）各自重複定義同一路徑邏輯而不同步。"""
    return Path(settings.workspace_dir) / "_staging"


def task_queue_db_path() -> Path:
    """`task_queue.db` 的存放位置，對應 § 3.1.2 `ENQUEUE`／`RESTART` 節點——
    單一本地 SQLite 檔案，服務全部 KG 共用的抽取佇列效能索引，不隨個別 KG
    資料夾搬移。"""
    return Path(settings.workspace_dir) / "task_queue.db"
