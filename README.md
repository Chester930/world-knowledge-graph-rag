# World Knowledge Graph RAG

多場景知識圖譜 RAG 系統。將文件轉化為結構化 SVO 知識圖譜，透過雙層路由（ConceptNode + BFS 圖遍歷）提供精準問答。

> 本專案（World Knowledge Graph RAG）是 [knowledge-base-ai](https://github.com/Chester930/knowledge-base-ai)（智慧知識庫，個人研究專案）的重新架構與品牌化版本，同時作為論文研究的實作載體。原專案驗證了核心概念的可行性；本專案的目標是在架構嚴謹度、可測試性與可維護性上系統性提升，並發展為涵蓋網頁與軟體、可支撐產品化的完整平台。

## 狀態

🚧 架構骨架階段 — 前後端骨架已建立並可啟動：

- **後端**：FastAPI app 可正常匯入與啟動，`core/`（設定、Neo4j 連線、LLM/Embedding provider 工廠與五種 provider 實作）已可運作；`routers/` → `services/` → `repositories/` 三層已接好，但 `services/` 內的核心演算法（SVO 抽取、ConceptNode 路由、BFS 圖遍歷、自我精煉迴圈）仍是 `NotImplementedError` 待重新設計後實作。
- **前端**：`ui/templates/index.html` + `ui/static/css` + `ui/static/js` 的基本聊天室版面（KG 側欄、暫存區、聊天串流）已建立，串接對應 API，等後端邏輯補上即可運作。

架構決策待補記錄於 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 核心特性（承襲自 v1，架構將重新設計）

| 特性 | 說明 |
|------|------|
| **多場景 KG** | 每個知識圖譜獨立管理 |
| **語意關係抽取** | SVO 三元組以精確語意類型儲存，非模糊向量 |
| **雙層 RAG 路由** | ConceptNode embedding 路由 → BFS 圖遍歷 → 圖譜驅動文件選取 |
| **多 Provider** | Ollama / OpenAI / Anthropic / Gemini / Grok，本地雲端自由切換 |

## 技術棧

| 元件 | 說明 |
|------|------|
| FastAPI | 後端 API，SSE 串流 |
| Neo4j | 知識圖譜資料庫 |
| sentence-transformers | 本地 embedding |
| Vanilla JS | 前端，無框架依賴 |

## 目錄結構

```
├── core/
│   ├── config.py             # 所有 .env 設定（唯一入口）
│   ├── database.py           # Neo4j AsyncDriver 連線 + KG 專用資料庫管理
│   ├── auth.py                # X-API-Key 驗證中介層
│   ├── constants.py          # 路由權重、SVO 語意關係類型等常數
│   └── providers/
│       ├── base.py           # LLMProvider / EmbeddingProvider 抽象介面
│       ├── factory.py        # init_providers() 工廠
│       ├── llm/              # ollama, openai, anthropic, gemini, grok
│       └── embedding/        # local, openai, ollama
│
├── models/                   # Pydantic 資料模型（document, knowledge_graph）
├── repositories/              # Neo4j CRUD（concept_repo 已實作向量索引，其餘待補）
├── routers/                  # FastAPI 路由（documents, search, agent, knowledge_graph, staging）
├── services/                 # 核心業務邏輯（stub，待架構重整後實作）
├── ui/
│   ├── templates/index.html  # 前端頁面骨架
│   └── static/{css,js}       # 樣式與聊天室邏輯
├── tests/                    # pytest 測試套件
├── docs/                     # 架構與設計文件
└── main.py                   # FastAPI 應用進入點（lifespan 連線 + 路由掛載）
```

## 快速啟動

```bash
cp .env.example .env
# 編輯 .env，至少填入 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 與 LLM_PROVIDER

pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

## 授權

MIT License — 詳見 [LICENSE](LICENSE)
