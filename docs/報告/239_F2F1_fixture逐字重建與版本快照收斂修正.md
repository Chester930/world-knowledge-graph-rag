# 報告239：F2 fixture 逐字重建與 F1 版本快照收斂修正

> 本報告依報告238 執行 F2 → F1；未連 Neo4j、未啟動 Ollama／WSL、未呼叫 LLM／embedding／外網，也未執行 collector 程式。
> 姊妹專案只讀 `data/processed/moj_laws/*.json`；報告236／237 原文未修改。本報告結果仍待規劃對話獨立驗證。

## 1. F2：真實 fixture 逐字重建

來源檔：`labor-compliance-collector/data/processed/moj_laws/moj_history_20260819T093233Z-history.json`。

- 來源筆數 209，SHA-256：`3a8aceb9c176fb98ea6cc5cacbba0843daa46385ce08d30b538de62448129d40`。
- 重建 12 筆：N0030001 第 2／3／8 條、N0030006 第 7／9／12 條，各含舊版與現行版。
- 所有來源欄位與 `content` 完整保留，包含 `category`、`law_name` 的「 EN」後綴，以及 N0030006 第 12 條完整導覽雜訊尾巴；`tests/fixtures/README.md` 逐筆列出 `version_id` 與 `content` SHA-256。
- 自洽測試逐筆檢查：`sha256(content) == content_hash`、`sha256(f"{pcode}|{article_no}|{valid_from}|{content_hash}") == version_id`，12／12 通過。導覽截尾另以測試內合成字串示範，沒有冒充真實材料。

重跑既有示範後，描述性計數未變：6 條鏈／12 個版本／30 個事件／6 條含異常鏈／0 互斥違規；JSON 已重產，沒有改寫報告237。

## 2. F1：版本快照收斂

`services/law_version_events.py` 仍是純運算、零接線。先沿用報告236 的 `(pcode, article_no, version_id)` canonical 去重，再以 `(pcode, article_no, valid_from, normalize_content(content))` 收斂；正規化沿用 NFKC、移除導覽雜訊與空白。

- 同一收斂鍵的代表列取 `retrieved_at` 最大者；完全缺席時取輸入順序最後一列。
- 同一 `valid_from` 但正規化內容不同時保留為不同版本，輸出 `same_valid_from_different_content`，不靜默合併。
- 輸出 `snapshot_collapses`、`snapshot_field_conflicts`；欄位衝突只回報、不修正。
- `current_flag_anomalies` 與 `exclusivity_violations` 分開：前者是來源 `is_current` 旗標品質，後者只檢查事件重播後的「有效」狀態。current 摘要以 distinct `version_id` 計數，避免同一版本在多個 snapshot 的觀測列被重複計數。

### 2.1 完整來源執行結果

四檔來源原始 750 筆；沿用 P1 canonical 後輸入 220 筆。F1 結果如下：

| 項目 | 結果 |
| --- | ---: |
| 條文鏈 | 111 |
| 收斂後版本 | 209 |
| 事件 | 516 |
| `snapshot_collapses` 收斂群 | 4（勞基法第86條舊／現行各1群；請假規則第12條舊／現行各1群） |
| `snapshot_field_conflicts` | 4 群；只回報欄位差異 |
| 收斂前多 current 條文 | 2（N0030001 第86條、N0030006 第12條） |
| 收斂後 0／多 current 條文 | 0／0 |
| `same_valid_from_different_content` | 0 |
| `exclusivity_violations` | 0 |

勞基法第 86 條與勞工請假規則第 12 條均由多個 snapshot `version_id` 收斂為 1984／2024 或 2023／2025 兩版；代表列依最新 `retrieved_at` 選取。其餘 96 條雙版本與 13 條單版本維持原有版本數。

### 2.2 不退步比對

以收斂前 canonical 220 筆重播作為舊行為基線，排除實際發生收斂的第 86／12 條後，109 條鏈逐版本比對 `final_state` 與事件序列，差異 **0**。原有 12 筆 fixture 亦無收斂群，示範計數維持 6／12／30。

## 3. 測試與限制

- F2／F1 focused pytest：16 passed／0 failed。
- 未修改 collector、KG#4、Neo4j、Ollama、既有執行路徑、儲存欄位、報告236／237、論文或題庫。
- 本次完整來源重播以報告236 已定義的 version_id canonical 作為輸入；原始 750 個 snapshot 列若直接視為獨立輸入，會重複計算同一 `version_id` 的觀測列，故報告數字明確區分 750→220→209 三個階段。

**狀態：F2／F1 執行完成，等待規劃對話獨立驗證。**
