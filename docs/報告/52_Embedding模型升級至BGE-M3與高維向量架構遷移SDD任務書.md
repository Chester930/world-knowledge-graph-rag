# 52 Embedding 模型升級至 BGE-M3 與高維向量架構遷移 SDD 任務書

> **建立日期**：2026-09-15  
> **文件性質**：系統模型替換與維度遷移任務書（供 Codex / 協同 Agent 直接執行）  
> **關聯論文章節**：`docs/論文/03_系統設計與方法論.md` §3.1.3、§3.2 §b、§5.4.1（向量索引與相似度度量）  
> **關聯程式模組**：
> - `core/config.py`
> - `core/constants.py`
> - `core/providers/factory.py`
> - `core/providers/embedding/ollama.py`
> - `core/providers/embedding/local.py`
> - `repositories/concept_repo.py`
> - `services/svo_service.py`
> - `services/cluster_service.py`

---

## 1. 模型背景與相容性確認（User Verification）

### 1.1 Ollama 本地 `bge-m3` 與 `BAAI/bge-m3` 是否相同？
* **確認結論：完全是一模一樣的模型。**
  * 經終端 `ollama list` 查驗，本機已預先安裝 `bge-m3:latest`（ID: `790764642607`，1.2 GB）。
  * Ollama 的 `bge-m3` 係將北京智源研究院官方之 `BAAI/bge-m3` 權重轉換為 GGUF 量化格式封裝而成。
  * **核心規格**：
    * 最大上下文長度：**8,192 Tokens**（徹底根除 MiniLM 128 tokens 之嚴重截斷問題）。
    * 輸出向量維度：**1,024 維**。
    * 多語言與繁體中文支援能力名列開源頂級。

---

## 2. 升級至 BGE-M3 的連鎖影響與遷移架構

將 Embedding 模型由舊有的 `paraphrase-multilingual-MiniLM-L12-v2`（384 維）升級至 `bge-m3`（1,024 維），屬於破壞性維度變更（Breaking Change），必須同步更新以下三個層級：

```
                      【BGE-M3 模型 (1024 維 / 8192 Context)】
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
【1. 設定與常數層】              【2. 記憶體與快取層】             【3. Neo4j 向量索引層】
- config: bge-m3                - 廢除舊 .npy (384 維)           - 刪除舊 384 維 Index
- constants: VECTOR_DIM = 1024  - 清除舊 prototype 快取          - 重建 1024 維 Index
```

### 2.1 維度不相容陷阱（Dimension Mismatch）
* 舊系統寫死 `VECTOR_DIM = 384`。
* Neo4j 在執行向量索引查詢（如 `db.index.vector.queryNodes`）時，若傳入的向量維度與宣告的索引維度不合，會直接拋出 `CypherExecutionException` 阻斷服務。
* 本任務書規範：**全面提升至 1024 維，並支援自適應動態探測。**

---

## 3. 具體修改規格清單（供 Agent 執行）

### 3.1 設定檔更新：`core/config.py` 與 `.env`
1. 修改 `core/config.py` 預設值：
   ```python
   # 預設改為 bge-m3
   ollama_embedding_model: str = "bge-m3"
   local_embedding_model: str = "BAAI/bge-m3"
   ```
2. 若系統運行於 Ollama 環境，`.env` 配置建議：
   ```bash
   EMBEDDING_PROVIDER=ollama
   OLLAMA_EMBEDDING_MODEL=bge-m3
   ```
   *(註：若顯卡 VRAM 充裕，亦可走 `EMBEDDING_PROVIDER=local` 搭配 `BAAI/bge-m3`)*

### 3.2 常數更新：`core/constants.py`
1. 更新全域向量維度常數：
   ```python
   # 修改前：
   # VECTOR_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2
   
   # 修改後：
   VECTOR_DIM = 1024  # BAAI/bge-m3 (8192 max tokens)
   ```

### 3.3 Neo4j 向量索引重建與相容性檢查：`repositories/concept_repo.py`
1. 檢視建立向量索引的 Cypher 腳本（搜尋 `db.index.vector.createNodeIndex`）：
   ```cypher
   // 確保 vector.dimensions 參照 constants.VECTOR_DIM (1024)
   CALL db.index.vector.createNodeIndex(
       'concept_embedding_idx',
       'ConceptNode',
       'embedding_vector',
       1024,
       'cosine'
   )
   ```
2. 在啟動前或遷移腳本中，若偵測到既有索引維度為 384，應支援安全刪除並重建：
   ```cypher
   DROP INDEX concept_embedding_idx IF EXISTS
   ```

### 3.4 清理過期向量快取
* 由於舊有快取（如 `_prototype_cache.json`、`baseline_rag_index_*.npy`）均為 384 維，混合 1024 維會引發矩陣運算形狀錯誤（ValueError: operands could not be broadcast together）。
* 執行指令或腳本清空所有舊向量快取檔案。

---

## 4. 驗收標準（Definition of Done）

- [ ] `core/config.py` 與 `core/constants.py` 正式將預設模型導向 `bge-m3` 且維度為 `1024`。
- [ ] 執行單元測試探測維度：
  ```python
  provider = get_embedding_provider()
  vec = await provider.encode("測試法規文字")
  assert len(vec) == 1024
  ```
- [ ] 傳入超過 500 字之長文本（例如整段 800 字之勞基法罰則條文），確認向量輸出正常且未被 128 tokens 截斷。
- [ ] Neo4j 向量存取與 `cluster_service` 分群運算無維度報錯。
