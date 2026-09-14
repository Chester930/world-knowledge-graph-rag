# 46 領域可插拔切塊參數化與主旨錨定 SDD 任務書

> 建立日期：2026-09-14  
> 狀態：規劃定案，準備動工  
> 關聯論文章節：`docs/論文/03_系統設計與方法論.md` §3.1.2、§3.9（全生命週期參數驅動架構）  
> 關聯程式模組：`core/kg_config/model.py`、`services/svo_chunking.py`、`tests/services/test_svo_chunking.py`

> ⚠️ **編號訂正（2026-09-14，入庫時補記）**：本文件原編號 45，建立時只存在主要 checkout 目錄、從未 `git commit`，因與已入庫的報告44/45 衝突改編號 46。**本文件描述的實作是否已經完成，尚未經查證**——見入庫時的程式碼審查結果。

---

## 1. 核心哲學：零代碼生成（Zero Code-Gen）與宣告式參數驅動

### 1.1 問題與架構原則
在面對多領域知識圖譜（如法規、合約、技術標準、金融審計）時，常見的一種「反模式（Anti-Pattern）」是為每個新領域或新圖譜動態生成專屬的 Python 程式碼（Code-Gen / Code-as-Configuration）。
本專案嚴格確立架構紀律：
- **核心引擎 100% 固化（Universal Static Engine）**：全系統的 Python 程式碼完全固化通用，絕對不因為新增不同 KG 或不同領域而動態生成或改寫 Python 程式碼。
- **特異性 100% 參數化（Declarative Configuration Profiles）**：各領域與各 KG 的差異，全部以嚴格型別化（Pydantic）的 JSON/YAML 設定檔描述（如 `DomainPack`、`per-KG profile`）。
- **單一行程服務多 KG（Multi-tenant Safety）**：所有設定物件均為不可變（`frozen=True`），同一執行程序可無競爭地服務不同領域設定的知識圖譜。

### 1.2 全流程七大關卡之參數控制覆蓋
本哲學貫穿知識圖譜生命週期的全部七大關卡：
1. **結構解析與切塊（Ingestion & Chunking）**：由 `ChunkingConfig` 控制切塊視窗大小、法條主旨識別正則、子款項前綴主旨繼承。
2. **SVO 語意抽取（Extraction & Prompting）**：由 `ExtractionConfig` 與 `DomainConfig` 控制領域提示詞模板、受控關係類型庫、Few-shot 正反例。
3. **實體消歧與對齊（Alignment & Dedup）**：由 `DedupConfig` 與 `guard_profile` 控制三區分類門檻、量測單位字典、CJK 序數正則。
4. **圖譜構建與特徵（Graph Ingestion & Indexing）**：由 `GraphSchemaConfig` 控制向量維度、UUID5 命名空間、批次大小。
5. **雙層檢索與自適應路由（Adaptive Routing & BFS）**：由 `RoutingConfig` 與 `BfsConfig` 控制行為樹分類權重、Cypher 扇出上限、樞紐種子度數上限。
6. **混合重排序與名額融合（Hybrid Reranking & Fusion）**：由 `FactListConfig` 控制 RRF 參數、Zigzag 重排門檻、BFS 鄰居剪枝上限。
7. **確定性接地守衛（Deterministic Guarding）**：由 `GuardConfig` 與 `RefusalConfig` 控制法律時效錨點關鍵詞、條號正則驗證式、法定拒答句式。

---

## 2. 本階段核心聚焦：切塊參數化與主旨錨定（Header Anchoring）

### 2.1 痛點分析：款式斷頭（Clause Truncation）
目前 `services/svo_chunking.py` 預設為純固定句數滑動視窗（5 句滑動視窗，重疊 2 句）。
在法規或結構化條文中，條文結構常為：
> **第 40 條**：雇主有下列情事之一者，處新臺幣三萬元以上十五萬元以下罰鍰：  
> 一、...  
> 二、...  
> 三、...  
> 四、未依法提供必要防護設備...  
> 五、...

若第 4 款、第 5 款被切分進第二個 Chunk，此區塊內僅有列舉款項，**完全遺失了母條文的首句條旨（「雇主」、「處新臺幣三萬元以上十五萬元以下罰鍰」）**。LLM 接收到此區塊時，抽出的 SVO 三元組將失去法律主體與法律效果，造成知識圖譜嚴重的語意斷裂與檢索失真。

### 2.2 解決方案：通用主旨錨定（Header Anchoring）
- **通用代碼層**：在 `services/svo_chunking.py` 內建支援 `header_anchored` 策略。
- **宣告式參數層**：由 `ChunkingConfig` 宣告正則式與繼承旗標。

```python
class ChunkingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    
    strategy: Literal["sliding_window", "header_anchored"] = Field(
        default="sliding_window",
        description="切塊策略：sliding_window（通用純句數滑動視窗）或 header_anchored（主旨前綴錨定）"
    )
    max_sentences: int = Field(default=5, ge=1, le=50, description="單塊最大句數")
    overlap_sentences: int = Field(default=2, ge=0, le=20, description="相鄰塊重疊句數")
    header_regex: str | None = Field(
        default=None,
        description="條旨/主旨識別正則表達式，例如 r'^第[一二三四五六七八九十百千0-9]+條'"
    )
    prepend_header_to_children: bool = Field(
        default=True,
        description="當條文跨 Chunk 切分時，是否自動將母條文首句條旨作為前綴注入至子款項 Chunk"
    )
    max_chunk_chars: int = Field(default=1000, ge=100, le=10000, description="單塊字元軟上限")
```

### 2.3 演算法細節與血統不變式（Lineage Invariant）
1. **主旨識別**：
   - 遍歷句子清單，若句子匹配 `header_regex`，將該句標記為當前活動主旨（`current_header`）。
2. **區塊組裝**：
   - 當產生 Chunk 時，若 `prepend_header_to_children=True` 且當前區塊的首句不是該條文的主旨行本身，通用引擎自動將 `current_header` 前綴於該 Chunk 的 `text` 內容前（並以換行區隔）。
3. **血統不變式（Lineage Invariant）**：
   - 前綴主旨純粹作為 **LLM SVO 抽取的語意上下文提示**。
   - `SVOChunk.source_sentence_start` 與 `SVOChunk.source_sentence_end` **嚴格維持該子款項於 `original.md` 中的真實實體句子行號範圍**。
   - `SVOChunk.original_sentences` 與 `SVOChunk.normalized_sentences` 保持 1:1 精確對映，索引完全不發生偏移。

---

## 3. 實作計畫與驗收標準

### 3.1 實作檔案
1. `core/kg_config/model.py`：新增 `ChunkingConfig`，並將其納入 `KGConfig`。
2. `services/svo_chunking.py`：
   - `build_svo_chunks()` 擴充支援 `config: ChunkingConfig | None = None` 參數。
   - 實作主旨錨定與前綴注入邏輯。
3. `config/domain_packs/taiwan-labor-law.json`（若存在）或預設設定：配置法規專屬 `header_regex`。

### 3.2 驗收測試（Test Specifications）
- **Test 1：向下相容驗證（Default Sliding Window）**
  - 不提供 `config` 或 `strategy="sliding_window"` 時，切塊結果與原有的 5 句/重疊 2 句邏輯 100% 逐字一致。
- **Test 2：主旨錨定前綴注入（Header Anchored Injection）**
  - 測試多款項條文，確認第一塊包含主旨，第二塊（款四、款五）開頭成功注入母條文主旨。
- **Test 3：血統行號不變式驗證（Lineage Boundary Integrity）**
  - 斷言第二塊注入主旨後，其 `source_sentence_start` 與 `source_sentence_end` 依然等於實際款式行號，未被主旨行篡改。
- **Test 4：全套測試無回歸（Regression Zero）**
  - 既有 19 項新評測測試與 `test_svo_chunking.py` 全數 PASS。
