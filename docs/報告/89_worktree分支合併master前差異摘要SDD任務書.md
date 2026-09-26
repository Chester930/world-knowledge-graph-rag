# 89 worktree分支合併master前差異摘要SDD任務書（**交付 Codex，純分析報告，不執行合併**）

**建立日期**：2026-09-26
**文件性質**：交付 Codex 執行用任務書。**只產出一份差異摘要報告，絕對不執行任何合併、rebase、push 到 master 的操作**。目的是讓使用者與 Claude Code 在合併前，先看清楚這個分支跟 `master` 之間的完整差異範圍與衝突風險，再由人決定要不要合併、怎麼合併。
**分支／工作區**：`worktree-sdd-retrieval-comparison`，`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`

---

## 0. 一頁摘要

本 worktree 分支（`worktree-sdd-retrieval-comparison`）領先 `origin/master` **97 個 commit**（報告64以後的所有工作，含這次 session 的報告75-88全部內容）。**⚠️ 關鍵事實**：`origin/master` 同時也領先這個分支 **54 個 commit**——也就是說，這不是單純的「這個分支超前，直接 fast-forward 到 master 就好」的情況，master 自己也有這個分支沒有的獨立進度，合併時**有可能出現檔案衝突**。

本任務要做的是：**把這兩邊的差異範圍與潛在衝突整理清楚，供人判斷**，不是去解決衝突或執行合併。

---

## 1. 任務清單

### T1（M）：確認分岔基準與雙向落差

- `merge-base`：`b1c620eac23dadce4b70d079cc83993c25de78ee`（已查證，直接引用，不需要重新算）。
- 分支領先 `origin/master`：97 個 commit（`git log origin/master..HEAD --oneline`）。
- `origin/master` 領先本分支：54 個 commit（`git log HEAD..origin/master --oneline`）。
- 請完整列出 `origin/master` 這 54 個領先 commit 的訊息摘要（`git log HEAD..origin/master --oneline`），這是本分支完全不知情的 master 端進度，合併前必須知道 master 這段時間做了什麼。

### T2（L）：本分支變更的分類摘要（不要逐檔羅列 `data/eval/` 底下的產生型資料）

依目錄分類彙整 `git diff --stat origin/master...HEAD`（注意用三個點 `...`，即以 merge-base 為基準比較兩邊，不是 `..`）：

1. **production 程式碼**（`services/`／`core/`／`routers/`／`models/`）：逐檔列出，簡述這個檔案的變更屬於哪一份報告（例如 `services/svo_service.py` 的變更對應報告76/77/79等）、變更性質是「新增per-KG設定機制（預設零行為變化）」還是「修改既有邏輯」——**特別標註有沒有任何一處改動了`chat()`或其他production路徑的預設行為**（依這次session的執行紀律，應該全部都是預設關閉/零行為變化的新增機制，但請實際核對，不要假設）。
2. **`data/eval/test_cases.json`**：本分支對這個檔案做了幾次修改（哪些 commit）、`bank_sha256` 從什麼變成什麼、原因（比照報告85 commit message 的既有說明）。
3. **`docs/論文/`**：逐檔列出改了哪幾章、對應哪些報告（例如 00/05/06/07 對應報告80/83/86）。
4. **`docs/報告/`**：**只需要列出新增的報告檔名清單與數量**（報告64之後到88，約25份），不需要逐份摘要內容——這些報告本身已經是完整記錄，不需要在這裡重複。
5. **測試檔案**（`tests/`）：列出新增/修改的測試檔案與大致新增測試數量。
6. **`data/eval/` 底下的資料檔案**：**不要逐檔列出**（有158個檔案變更，多數是評測產出的 records/summary JSON）。改成依資料夾分類統計（例如：「`baseline_runs/20260923_rebased/` 新增N個檔案，為S0基準評測產出」「`candidate_runs/s3_chunk_rag_*` 新增N個檔案，為S3對照組評測產出」），說明每個分類的資料來源與用途（可引用對應報告編號），不需要條列每個 `records.json` 的內容。
7. **`HANDOVER.md`**：說明本分支這段期間累積了多少次更新（不需要逐條列，只需要總結大致涵蓋哪些階段）。

### T3（L，本任務最重要的部分）：衝突風險評估

- 取得 `origin/master` 這 54 個領先 commit 改動過的檔案清單（`git diff --name-only b1c620e..origin/master`）。
- 取得本分支這 97 個 commit 改動過的檔案清單（`git diff --name-only b1c620e..HEAD`）。
- **交叉比對兩份清單，找出兩邊都改過的檔案**——這些是合併時真正有衝突風險的地方，逐一列出並簡述：master 端改了這個檔案的什麼、本分支改了這個檔案的什麼，兩者是否可能是同一段落/同一函式（高衝突風險）還是各自獨立的不同段落（低衝突風險，git通常能自動合併）。
- **特別注意**：`HANDOVER.md`、`docs/論文/00_研究追溯對映表.md` 這類長期累積、多方都會寫入的檔案，大概率兩邊都有修改，衝突機率高，請重點核對。
- 若交叉比對後發現「兩邊都改過的檔案」清單很長，不需要每一個都詳細分析衝突內容，可以先列出清單、標註高低風險等級，供人類決定要不要進一步細看。

### T4（S）：明確結論與建議（僅供參考，不代表核准合併）

- 總結：這次合併是否單純（無衝突檔案）、還是有需要人工處理的衝突。
- 若有衝突風險檔案，建議合併時的處理順序或分批方式（例如「先合併data/eval與docs/報告等純新增內容，衝突風險檔案留到最後單獨處理」），但**這只是建議，不是你要做的決定，也不是你要執行的動作**。

---

## 2. 明確不要做的事（本任務最重要的紅線）

- **絕對不要執行 `git merge`、`git rebase`、`git checkout master`、或任何會改變 `master` 分支狀態的操作**。
- **絕對不要 push 任何東西到 `master`**（不論是這個 worktree 分支的內容，或任何合併結果）。
- **絕對不要嘗試解決發現的衝突**——本任務只回報衝突風險在哪裡，不動手處理。
- **絕對不要修改任何程式碼、設定檔或既有報告內容**——本任務只讀取 git 歷史與 diff，產出一份新的分析報告。
- 不需要呼叫 Neo4j、Ollama，或執行任何測試。

## 3. 完成定義

1. T1-T4 全部完成，結果寫成新報告檔案 `docs/報告/89_worktree分支合併master前差異摘要結果.md`。
2. T3 的衝突風險評估必須明確列出「兩邊都改過的檔案」清單，不能只說「可能有衝突」而不給出具體檔案名單。
3. `git diff --stat` 只顯示新增的這一份結果報告檔案，**沒有任何其他檔案被改動**（尤其確認沒有任何 git 分支操作發生，`git branch --show-current` 執行前後應該仍是 `worktree-sdd-retrieval-comparison`，`master` 分支狀態完全未被觸碰）。
4. 這份報告是給人看的決策參考，語氣應該是「以下是客觀差異與風險，由使用者與Claude Code決定如何合併」，不要自己下「建議直接合併」這種逾越本任務授權範圍的結論。

---

## 4. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/89_worktree分支合併master前差異摘要SDD任務書.md` 的 T1-T4。**這是純分析報告任務，絕對不能執行任何 `git merge`／`git rebase`／push 到 master 的操作**，只讀取 git 歷史與 diff、產出一份新報告。
>
> 背景：這個 worktree 分支領先 `origin/master` 97 個 commit，但 `origin/master` 也領先這個分支 54 個 commit（不是單純 fast-forward 的情境）。任務書已提供 `merge-base`（`b1c620eac23dadce4b70d079cc83993c25de78ee`）與雙向 commit 數，你需要：①完整列出 master 端這54個commit在做什麼；②依目錄分類（production程式碼／`test_cases.json`／`docs/論文`／`docs/報告`／測試／`data/eval`資料／`HANDOVER.md`）摘要本分支的變更，`data/eval` 底下158個檔案不要逐檔列出，依資料夾分類統計即可；③**最重要**：交叉比對兩邊各自改過的檔案清單，找出「兩邊都改過」的衝突風險檔案並列出，特別注意 `HANDOVER.md`／`docs/論文/00_研究追溯對映表.md` 這類長期累積的檔案。
>
> 結果寫成新報告 `docs/報告/89_worktree分支合併master前差異摘要結果.md`。這份報告只是給使用者跟 Claude Code 判斷合併方式用的客觀資訊，不要自己下「建議合併」之類逾越授權的結論。完成後確認沒有任何 git 分支狀態被改動（`master` 完全未被觸碰），`git diff --stat` 只顯示新增的這份報告檔案。commit 前不需要額外詢問，但 push 需要使用者另行同意。
