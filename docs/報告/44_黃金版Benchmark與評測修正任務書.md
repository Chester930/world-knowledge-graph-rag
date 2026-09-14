# 報告 44：黃金版 Benchmark 與評測修正任務書

**建立日期**：2026-09-14  
**用途**：交由 Claude Code 執行後續資料、評測與報告修正  
**狀態**：任務規格已確認；本文件建立時尚未修改既有程式碼、報告 42 或題庫內容。  
**主要依據**：

- `docs/報告/42_全量重抽三階段方法比較與報告39七路評分報告.md`
- `docs/附錄A題庫.json`
- Gemini 提出的「Exact Substring + Dual-LLM Cross-Validation + Atomic Facts」建議

> ⚠️ **編號與內容訂正（2026-09-14，入庫時補記）**：本文件建立時只存在於主要 checkout 目錄、從未 `git commit`，因此兩個並行工作的 Claude session 都查不到它，各自獨立把自己的設計報告編號為「43」——`docs/報告/43_Fact-RAG語意排名健壯性設計報告.md`（另一 session 所作，已先行 commit 進 `origin/master`）因此保留 43 號，本文件改編號為 44 以入庫，避免編號衝突。
>
> **§2.1 的診斷措辭已過時，需與報告41 §9 對照**：本文件寫作時認為「26-Q5 的根因目前不能宣稱為純生成端」「尚不能只靠 facts=1 證明正確的 §3 Fact 已進入 prompt」——這個判斷在寫作當下是合理的保留。但另一 session 隨後（同日）直連 Neo4j 查證，確認：(1) Fact 節點確實存在、`source_doc_id` 正確；(2) K/K-2b 的事實清單（`facts=1`）從未包含 §3「當月一日」內容，只有 §2；(3) 目標事實在 `vector_search_facts()` 全域語意排名第 41 名，被 34 條跨文件同義雜訊擠出 `top_k=20`——**已經比本文件 §2.1 的「尚不能宣稱」更進一步，明確定位到失效發生在檢索端（Fact-RAG 全域排名），不是序列化或生成端**。完整查證見 `docs/報告/41_檢索文件範圍改用實體錨定設計報告.md` §9 與 memory `project_report39_retrieval_comparison_harness`。
>
> 這個更新不代表本文件（黃金版 Benchmark 方法論升級）失去價值——atomic gold facts／retrieval lineage／確定性接地檢查對整體評測嚴謹度仍有獨立意義，且能反過來驗證報告41 §9／報告43（Fact-RAG 排名健壯性）診斷與修法是否正確——但執行時應以報告41 §9 的診斷為準更新本文件 §2.1 的措辭，而非重新從「不確定根因」的假設出發。

---

## 1. 任務目標

將目前以自然語言 `gold_answer` 及人工 0/1/2 評分為主的評測，升級為：

1. 直接根據原始法規建立的 atomic gold facts。
2. 每個事實具有可追溯的原文 span、條文位置與來源版本。
3. 以確定性規則檢查數字、單位、日期、否定、條件、例外與引用條號。
4. 將 retrieval、Fact 序列化與 generation 的錯誤分開診斷。
5. 保留目前 0/1/2 分數作為輔助摘要，但不再作為唯一正式指標。

---

## 2. 已確認、不可再延後的問題

### 2.1 26-Q5 的根因目前不能宣稱為純生成端

報告 42 §6.4 宣稱 K/K-2b 已檢索到「自災害發生之當月一日起」，因此錯誤是生成端 paraphrase。但附錄中 K/K-2b 展示的事實清單主要只有 §2 的「災後六個月期間」事實，沒有完整展示 §3 的起算日原文。

目前只能確定：錯誤發生在 KG 路徑的檢索／Fact 序列化／生成鏈上；尚不能只靠 `facts=1` 證明正確的 §3 Fact 已進入 prompt。

> ⚠️ 見文首「編號與內容訂正」——此節措辭已被報告41 §9 的直接查證更新：失效已定位到檢索端（`vector_search_facts()` 全域排名第41），非序列化或生成端。執行本文件任務時應同步更新此節。

### 2.2 `gold_facts` 目前仍為空

`docs/附錄A題庫.json` 的 metadata 明確記載 `gold_facts` 待補，個別題目也仍有 `[待核]` 或 `wording_status=gist`。這些項目完成原文核對前不得作為正式 benchmark 分數。

### 2.3 六題結果只能作為 pilot

報告 42 的正式七路比較只有 6 題、每 arm 3 run。三次 run 不能視為 18 個獨立題目，且 T2 的 26-Q5 同文件重測只能證明症狀可重現，不能視為不同題目的獨立根因證據。

---

## 3. P0 必做任務

### P0-1：修正報告 42 的措辭

修改 `docs/報告/42_全量重抽三階段方法比較與報告39七路評分報告.md`：

1. 將「三階段方法比較」改為「三階段流程、成本與抽取後七路消融比較」。抽取前與抽取中沒有多方法消融，不得寫成已完成方法比較。
2. 將 26-Q5 的結論改為：

   > 已確認錯誤發生於 KG 檢索／Fact 序列化至最終生成的路徑；現有紀錄不足以單獨證明為純生成端 paraphrase。

3. 將「B0/B1 優於 KG」限定為「本次六題 pilot 樣本中的觀察」。
4. 將 T2 Q5 描述為同症狀重現，不宣稱是獨立根因驗證。
5. 將 39.3 小時明確標示為「已知主要運行區段小計／下限」，不得解讀為完整有效運算時間。

### P0-2：建立原文獨立的 atomic gold facts

新增或修改 `docs/附錄A題庫.json`，先完成報告 42 使用的 6 題：

- 18-Q1
- 18-Q2
- 18-Q3
- 18-Q4
- 18-Q5
- 26-Q5

Gold 必須直接回到原始法規建立，不得以 KG Fact、B0/B1 答案或模型共識作為真值。KG Fact ID 可以作為追蹤欄位，但不能取代原文來源。

每個 atomic fact 至少包含：

```json
{
  "claim_id": "26-Q5-c2",
  "claim_type": "extracted",
  "subject": "災後六個月期間",
  "predicate": "starts_from",
  "object": "災害發生之當月一日",
  "modality": "must",
  "condition": null,
  "exception": null,
  "time_scope": "災後六個月期間",
  "critical_tokens": ["當月一日"],
  "required_spans": [
    {
      "source_doc": "N0050030",
      "article": "§3",
      "start": 0,
      "end": 0,
      "exact_span": "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月"
    }
  ],
  "forbidden_claims": [
    "自災害發生當日開始",
    "自災害發生日起算"
  ],
  "mandatory": true,
  "weight": 1
}
```

實際 `start`／`end` 必須依原始法規文字填入，不得保留範例中的 0。

必要欄位說明：

- `source_doc`、版本或抓取日期、原文 hash。
- `article`、paragraph、原文 offset。
- subject、predicate、object。
- 數值、單位、比較符號、期間。
- polarity、modality、condition、exception。
- `critical_tokens`：數字、日期、單位、否定與法律義務詞。
- `forbidden_claims`：常見錯答或反向答案。
- `claim_type`：原文事實、推導事實、拒答條件。
- 多跳題的 `derivation_steps`。

### P0-3：排除未完成題目

在正式 scorer 中加入 benchmark eligibility：

- `gold_facts` 為空：排除。
- `gold_answer` 含 `[待核]`：排除。
- `wording_status=gist` 且尚未完成原文回核：排除。
- 排除原因必須寫入結果，不得靜默跳過。

### P0-4：保存完整 retrieval lineage

每一筆問答結果都必須保存下列資料：

```text
raw retrieved chunks
raw retrieved facts
raw BFS triples
merged context lines
final prompt 或 prompt hash
model name/version
temperature/seed
input/output token 數
retry/re-generation 次數
final answer
```

至少要能回答：

1. 原始法規 span 是否被召回？
2. span 是否被抽成 Fact？
3. Fact 是否保留 critical token？
4. Fact 是否進入 merged context？
5. context 是否進入 final prompt？
6. 最終答案在哪一步改錯？

### P0-5：新增確定性接地檢查

新增或擴充 verifier，至少檢查：

1. exact span 是否存在於指定文件與指定條文。
2. offset 是否落在指定原文範圍。
3. 數字、單位、比較符號是否一致。
4. 日期與期間是否一致。
5. `得／應／不得／未滿／除外／原則上` 是否被改寫。
6. 引用條號是否存在於本次來源。
7. forbidden claim 是否出現。
8. 主詞、受詞與條件是否錯綁。

單純 `span in original_text` 不足以通過驗證；必須搭配 source locator 與 claim-to-span 對應。

### P0-6：加入 26-Q5 日期精度守衛

至少將下列內容視為不同語義，不得自動視為同義：

```text
當月一日
當月起
當日
當天
災害發生之日
災害發生日起
```

26-Q5 的 gold fact 必須要求 `當月一日`，並將其餘錯誤替代表述列為 forbidden claims。

### P0-7：建立 atomic scorer

正式評分至少輸出：

- atomic claim coverage。
- atomic claim precision。
- critical number/date accuracy。
- unsupported claim rate。
- contradiction rate。
- hallucination rate。
- correct refusal。
- false refusal。
- citation validity。
- question-level exact pass。

目前 0/1/2 分數可以保留作為人類可讀摘要，但不得再是唯一正式指標。

若要達成真正確定性評分，受測模型輸出也應要求結構化 claims 與 evidence span ID；若仍接受自由文字，必須明確標示「仍需要 claim extraction 層」。

---

## 4. P1 必做任務

### P1-1：建立 canary／negative 測試集

加入以下類型：

- 原文未記載。
- 答案存在於未提供的另一文件。
- 故意竄改數字。
- 相近但不同條文。
- 日期精度陷阱。
- 否定詞陷阱。
- 條件或例外被移除。
- 正確數字但錯誤主詞。
- 不存在的條號。

### P1-2：處理重複題

依 `dup_map` 或 underlying claim 分組。同一法律事實的不同問法不得直接視為完全獨立樣本。

### P1-3：補充實驗 manifest

每次正式實驗記錄：

```text
question set version
gold version
KG ID
code commit
model/version
prompt hash
retrieval parameters
temperature
seed
context limit
run timestamp
```

### P1-4：補充成本與延遲指標

報告每個 arm 的：

- median latency。
- P95 latency。
- input/output tokens。
- retry 次數。
- regeneration 次數。
- context facts/triples 數。
- timeout/error rate。

---

## 5. 不得擅自變更

Claude Code 執行時不得自行：

1. 更換模型或擴大模型版本比較範圍。
2. 把 KG Fact 直接當作 gold truth。
3. 將 `gist` 或 `[待核]` 題目納入正式分數。
4. 以兩模型一致直接判定為真值。
5. 刪除既有 run 結果或覆寫原始紀錄。
6. 把同一題的三次 run 當成三個獨立題目。
7. 在沒有 retrieval lineage 的情況下宣稱錯誤根因已定位。
8. 未經確認就更換 retrieval 架構或生成 prompt 的核心策略。

---

## 6. 驗收條件

本任務完成前，必須全部符合：

- [ ] 報告 42 的 26-Q5 根因措辭已改為暫定定位。
- [ ] 六題 pilot 皆有非空 `gold_facts`。
- [ ] 每個 gold fact 都有 source doc、article、offset、exact span。
- [ ] Gold 來源不是 KG Fact 或模型答案。
- [ ] 未核准題目不會進入正式 scorer。
- [ ] 每筆 run 都保存 retrieval lineage。
- [ ] 26-Q5 能區分 §3 原文在召回、Fact、merged context、prompt 的各階段狀態。
- [ ] 日期、數字、單位、否定與條號檢查可自動執行。
- [ ] scorer 能輸出 atomic coverage、precision、hallucination 與 refusal 指標。
- [ ] 原本 0/1/2 結果仍可追溯，不被刪除。
- [ ] 變更具備測試與版本紀錄。

---

## 7. 建議執行順序

1. 先讀取本文件、報告 42 與附錄 A。
2. 先修正報告 42 的不當結論與標題。
3. 建立六題 raw-source gold facts。
4. 實作 schema validation 與 eligibility filter。
5. 實作 source span、日期／數字／條號 verifier。
6. 加入 retrieval lineage logging。
7. 重跑六題 pilot，優先檢查 26-Q5。
8. 實作 atomic scorer。
9. 補 canary 題組與成本指標。
10. 執行測試並產出修正前後比較報告。

---

## 8. 變更紀錄

### 2026-09-14

- 建立本任務文件（原編號 43，入庫時因與 `docs/報告/43_Fact-RAG語意排名健壯性設計報告.md` 衝突改編號 44，見文首訂正段）。
- 記錄 Gemini 建議中可直接採用的部分：exact span、atomic facts、canary、雙模型獨立抽取。
- 記錄必要限制：雙模型一致不等於真值；`facts=1` 不等於正確 Fact 已進入 prompt。
- 將 26-Q5 的根因結論降級為「KG 檢索／序列化／生成鏈待分離」（入庫時註記：已被報告41 §9 進一步定位為檢索端 Fact-RAG 排名問題，見文首訂正段）。
- 尚未修改既有報告、題庫、程式碼或原始 run 結果。
