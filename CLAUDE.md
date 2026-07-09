# CLAUDE.md — 智慧知識庫 v2 (Knowledge Base AI v2)

本檔案提供 Claude Code CLI Agent 理解此專案所需的背景。

## 專案概覽

**多場景知識圖譜 RAG 系統（v2 重構版）**：將文件轉化為結構化 SVO 知識圖譜，透過雙層路由（ConceptNode + BFS 圖遍歷）提供精準問答。

本專案是 [knowledge-base-ai](https://github.com/Chester930/knowledge-base-ai)（v1）的重新架構版本，作為論文研究的實作載體。v1 已驗證核心概念可行；v2 的目標：

- 更嚴謹的分層架構（明確的 domain / infrastructure 邊界）
- 更高的可測試性（依賴注入、減少隱性狀態）
- 更完整的文件與設計紀錄，支援論文寫作所需的可追溯性

- **後端**：FastAPI + Neo4j + Ollama/OpenAI/Anthropic/Gemini/Grok
- **前端**：Vanilla JS 單頁應用（無框架）

## 目前狀態

前後端架構骨架已建立且可啟動（`python -m uvicorn main:app` 可正常匯入）：

- `core/`（設定、Neo4j 連線與 KG 專用資料庫管理、auth、五種 LLM provider + 三種 embedding provider）**已可運作**，直接沿用 v1 驗證過的實作，屬於通用基礎設施、非本次重整範圍。
- `routers/` → `services/` → `repositories/` 三層已建立並在 `main.py` 中掛載，`ConceptRepository.create_vector_index` 已實作；但 `services/` 內的核心演算法（SVO 抽取、ConceptNode 路由分數、BFS 圖遍歷、自我精煉迴圈）與 `repositories/document_repo.py`、`repositories/kg_repo.py`、`repositories/concept_repo.py` 的其餘方法皆為 `NotImplementedError` stub，等待架構重整後實作。
- `ui/templates/index.html` + `ui/static/{css,js}` 已建立基本聊天室版面（KG 側欄、暫存區分類、SSE 串流聊天），採模組化 HTML/CSS/JS 分離（v1 為 1500+ 行單檔 HTML，此為 v2 嚴謹化的第一步）。

架構調整（分層方式、模組邊界、演算法重新設計）將於後續逐步討論並落實，避免一次性大改動導致不可回溯。待決議事項見 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 目錄結構

```
├── core/
│   ├── config.py              # 所有 .env 設定（唯一入口）
│   ├── database.py            # Neo4j AsyncDriver 連線 + KG 專用資料庫管理
│   ├── auth.py                 # X-API-Key 驗證中介層
│   ├── constants.py           # 路由權重、SVO_REL_TYPES 等常數
│   └── providers/
│       ├── base.py            # LLMProvider / EmbeddingProvider 抽象介面
│       ├── factory.py         # init_providers() 工廠
│       ├── llm/                # ollama, openai, anthropic, gemini, grok（已實作）
│       └── embedding/          # local, openai, ollama（已實作）
├── models/                    # Pydantic 資料模型（document.py, knowledge_graph.py）
├── repositories/               # Neo4j CRUD（concept_repo 部分已實作，document/kg 為 stub）
├── routers/                   # FastAPI 路由（documents, search, agent, knowledge_graph, staging）
├── services/                  # 核心業務邏輯（全為 stub，待架構重整後實作）
├── ui/
│   ├── templates/index.html   # 前端頁面骨架
│   └── static/{css,js}        # 樣式與聊天室邏輯（模組化，非單檔）
├── tests/                     # pytest 測試套件
├── docs/                      # 架構與設計文件
└── main.py                    # FastAPI 應用進入點（lifespan 連線 + 路由掛載）
```

## 開發慣例

- 修改前先確認是否已有對應 v1 實作可參考（[knowledge-base-ai](https://github.com/Chester930/knowledge-base-ai)），但不直接複製貼上——依 v2 的分層原則重新設計後再實作。
- 架構決策（分層、邊界、模式）應記錄於 `docs/`，供論文引用與追溯。

## 測試

```bash
pip install -r requirements-dev.txt
pytest
```
