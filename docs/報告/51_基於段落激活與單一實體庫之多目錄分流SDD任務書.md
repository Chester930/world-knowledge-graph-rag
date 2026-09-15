# 51 基於段落激活與單一實體庫之多目錄分流 SDD 任務書

> **建立日期**：2026-09-15  
> **文件性質**：系統設計與實作任務書（供 Codex / 協同 Agent 直接執行）  
> **關聯論文章節**：`docs/論文/03_系統設計與方法論.md` §3.1.1（暫存區文件自動分群與分配歸屬）  
> **關聯程式模組**：
> - `core/constants.py`
> - `services/classify_service.py`
> - `services/cluster_service.py`
> - `services/document_record_service.py`
> - `tests/services/test_classify_service.py`

---

## 1. 需求背景與設計原則（First Principles）

本任務書針對專案第一階段「去哪裡找（檢索路由與資料集分區）」之三大痛點進行重構優化。

### 1.1 現狀痛點分析
1. **長文件向量稀釋（Semantic Dilution）**：
   * 現行 `classify_service.compute_document_vector()` 採用整份文件所有 Chunk 向量的「平均值（Mean-Pooling）」。
   * 當文件長達數千字且涵蓋多個不同法規或業務主題時，平均後的代表向量趨近於平庸雜訊，在空間中失去分類邊界銳利度。
2. **實體搬移的一刀切（Hard Partitioning & Mutation）**：
   * 現行 `assign_document_to_kg()` 採用 `shutil.move()` 將文件實體資料夾搬入單一 KG 目錄。
   * 若一份文件兼具「勞基法請假」與「職災補償」，該文件只能歸入一個目錄，導致另一目錄在日後檢索時出現 **100% 漏失（0 召回）**。
3. **儲存約束（User Constraints）**：
   * **不可拆散存取**：文件必須保持完整性，嚴禁將單一實體檔案拆碎分散存放於不同目錄，確保下游模型能取得完整的上下文篇幅。
   * **不可重複冗餘存取**：嚴禁在硬碟中對同一檔案進行多份複製（避免磁碟浪費與版本同步不一致）。

---

## 2. 核心架構架構設計

系統分為 **「儲存層（SSOT ＋ 虛擬目錄登記）」** 與 **「判定層（段落 Embedding 激活投票）」**：

```
                              【單一實體檔案 Central Store】
                                doc_001.txt (完整無拆分)
                                           │
                ┌──────────────────────────┴──────────────────────────┐
                ▼                                                     ▼
     [Chunk 1, Chunk 2, ..., Chunk N] (段落切塊)                 [原始完整文件內容]
                │                                                     ▲
  與各既有 KG Prototype 進行段落級 Cosine 比對                           │
                │                                                     │ (指針參照 / 不拷貝)
    ┌───────────┴───────────┐                                         │
    ▼                       ▼                                         │
【KG 1: 勞基法請假】    【KG 2: 職災補償】                               │
命中 Chunks ≥ 2         命中 Chunks ≥ 2                               │
    │                       │                                         │
    ▼                       ▼                                         │
寫入 KG 1 Manifest      寫入 KG 2 Manifest ───────────────────────────┘
(虛擬成員: doc_001)     (虛擬成員: doc_001)
```

### 2.1 儲存層：單一真理源（SSOT）與 Manifest 虛擬登記
* **實體檔案存放**：
  * 檔案統一放置於中央文件池（例如 `data/raw_documents/{doc_id}/original.txt` 或既有 `unassigned` 集中池）。
  * 任何操作**嚴禁調用 `shutil.move` 改變原始檔案唯一路徑**，亦**嚴禁調用 `shutil.copy` 複製檔案實體**。
* **分類目錄成員紀錄（Manifest Registry）**：
  * 每個 KG / 分類目錄維護一個輕量 JSON 登記表 `_members.json`（或相容於 `document_record_service`）：
    ```json
    {
      "kg_id": "labor_leave_kg",
      "assigned_documents": [
        {
          "doc_id": "doc_001",
          "matched_reasons": ["chunk_2", "chunk_3"],
          "max_similarity": 0.76,
          "assigned_at": "2026-09-15T11:00:00"
        }
      ]
    }
    ```
  * （可選）在作業系統支援環境下，可由配置項開啟建立軟連結（Symlink），讓檔案管理員視覺可見，但底層仍為單一實體磁區。

### 2.2 判定層：段落激活投票機制（Chunk-to-Folder Voting）
不再依賴全文 Mean-Pooling。改為檢驗「各段落是否有足夠強度的主題聚焦」：

1. **分段**：以文件既有切塊（如 1,000 字 SVO Chunk 或標準語意段落）逐一取得段落向量 $v_c$。
2. **相似度計算**：對每個目標 KG 的中心向量 $P_k$，計算該文件所有 Chunk 的相似度陣列：
   $$S_{c, k} = \cos(v_c, P_k), \quad \forall c \in \{1, \dots, N\}$$
3. **整份文件納入條件（滿足以下任一條件即掛入該 KG）**：
   * **條件 A（多點深度命中）**：
     $$\text{Count}\big(\{c \mid S_{c, k} \ge \tau_{\text{sim}}\}\big) \ge K_{\text{min\_hits}}$$
     * 預設：$\tau_{\text{sim}} = 0.68$（`CHUNK_ACTIVATION_THRESHOLD`），$K_{\text{min\_hits}} = 2$（`CHUNK_MIN_HITS`）。
     * 意義：至少有 2 個段落高度吻合該主題，排除單一偶然詞彙造成的偽陽性。
   * **條件 B（核心篇幅佔比）**：
     $$\frac{\text{Count}\big(\{c \mid S_{c, k} \ge \tau_{\text{sim}}\}\big)}{N} \ge R_{\text{min\_ratio}}$$
     * 預設：$R_{\text{min\_ratio}} = 0.15$（`CHUNK_MIN_RATIO`，佔比達 15% 以上）。

---

## 3. 程式碼修改規格（供 Agent 執行清單）

### 3.1 常數設定：`core/constants.py`
新增以下控制常數：
```python
# Chunk-level Activation & Multi-Folder Assignment (SDD-51)
CHUNK_ACTIVATION_THRESHOLD: float = 0.68   # 單段落命中相似度門檻
CHUNK_MIN_HITS: int = 2                    # 觸發整份文件歸類所需的最少命中段落數
CHUNK_MIN_RATIO: float = 0.15              # 觸發整份文件歸類所需的命中段落佔比軟門檻
ENABLE_VIRTUAL_MANIFEST_ASSIGN: bool = True # 啟用 Manifest 虛擬歸屬（取代實體搬移）
```

### 3.2 分類服務重構：`services/classify_service.py`

1. **新增段落投票分類函式**：
   ```python
   def classify_by_chunk_voting(
       chunk_vectors: list[list[float]],
       kg_prototypes: dict[str, list[float]],
       threshold: float = CHUNK_ACTIVATION_THRESHOLD,
       min_hits: int = CHUNK_MIN_HITS,
       min_ratio: float = CHUNK_MIN_RATIO,
   ) -> list[ClassifyResult]:
       """計算各 Chunk 對各 KG Prototype 的相似度，以多點激活投票決定歸屬"""
   ```
2. **重構 `assign_document_to_kg()`**：
   * 保留舊有向後相容參數 `move_physical: bool = False`。
   * 當 `ENABLE_VIRTUAL_MANIFEST_ASSIGN=True` 且 `move_physical=False` 時：
     * **不呼叫** `shutil.move()`。
     * 於目標 KG 目錄寫入或更新 `_members.json`，將 `doc_id` 及命中中繼資料附加至清單。
     * 同時更新 `document_record_service` 標記該文件關聯的所有 KG IDs（List of UUIDs）。

### 3.3 測試規格：`tests/services/test_classify_service.py`
新增以下驗收測試：
1. **`test_chunk_voting_multi_label_assignment`**：
   * 構造一份假文件，包含 5 個 Chunks：前 2 個與 KG-A 相似度 0.75，後 2 個與 KG-B 相似度 0.72，中間 1 個為中立無關段落。
   * 斷言：分類結果同時包含 KG-A 與 KG-B，且整份文件被標記為同時歸屬此兩者。
2. **`test_single_hit_rejection`**：
   * 構造一份文件僅有 1 個 Chunk 偶然高於 0.68，其餘皆極低。
   * 斷言：未達 `CHUNK_MIN_HITS=2`，不予指派，避免誤判。
3. **`test_no_physical_file_split_or_duplication`**：
   * 驗證檔案在被指派至多個 KG 後，磁碟上原始檔案仍只有一份實體路徑，且檔案內容完整無缺。

---

## 4. 驗收標準（Definition of Done）

- [ ] `core/constants.py` 補齊段落激活相關常數。
- [ ] `services/classify_service.py` 實作段落投票邏輯，廢除強制一刀切實體搬移。
- [ ] 執行 `pytest tests/services/test_classify_service.py` 全部測試通過。
- [ ] 原有既有測試無回歸（Zero Regressions）。
