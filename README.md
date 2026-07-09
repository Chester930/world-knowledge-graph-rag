# 智慧知識庫 v2

多場景知識圖譜 RAG 系統。將文件轉化為結構化 SVO 知識圖譜，透過雙層路由（ConceptNode + BFS 圖遍歷）提供精準問答。

> 本專案為 [knowledge-base-ai](https://github.com/Chester930/knowledge-base-ai) 的重新架構版本，作為論文研究的實作載體。原專案驗證了核心概念的可行性；v2 目標是在架構嚴謹度、可測試性與可維護性上進行系統性提升。

## 狀態

🚧 初始骨架階段 — 目錄結構已建立，核心邏輯尚待從 v1 重新設計與遷移。

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
├── core/                    # 設定、DB 連線、Provider 工廠
│   └── providers/           # LLM / Embedding Provider 實作
├── models/                  # Pydantic 資料模型
├── repositories/            # Neo4j CRUD
├── routers/                 # FastAPI 路由
├── services/                # 核心業務邏輯
├── ui/templates/            # 前端頁面
├── tests/                   # pytest 測試套件
├── docs/                    # 架構與設計文件
└── main.py                  # FastAPI 應用進入點
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
