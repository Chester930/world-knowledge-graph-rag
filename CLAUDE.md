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

初始骨架階段。目錄結構已依 v1 架構建立，尚未遷移實際邏輯。架構調整（如分層方式、模組邊界）將於後續逐步討論並落實，避免一次性大改動導致不可回溯。

## 目錄結構（暫定，沿用 v1 慣例）

```
├── core/                    # 設定、DB 連線、Provider 工廠
│   ├── config.py
│   ├── database.py
│   ├── constants.py
│   └── providers/
│       ├── factory.py
│       ├── llm/
│       └── embedding/
├── models/                  # Pydantic 資料模型
├── repositories/            # Neo4j CRUD
├── routers/                 # FastAPI 路由
├── services/                # 核心業務邏輯（SVO 提取、KG 建構、問答）
├── ui/templates/             # 前端單頁應用
├── tests/                   # pytest 測試套件
├── docs/                    # 架構與設計文件
└── main.py                  # FastAPI 應用進入點
```

## 開發慣例

- 修改前先確認是否已有對應 v1 實作可參考（[knowledge-base-ai](https://github.com/Chester930/knowledge-base-ai)），但不直接複製貼上——依 v2 的分層原則重新設計後再實作。
- 架構決策（分層、邊界、模式）應記錄於 `docs/`，供論文引用與追溯。

## 測試

```bash
pip install -r requirements-dev.txt
pytest
```
