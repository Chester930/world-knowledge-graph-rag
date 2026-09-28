# 報告102：論文對齊——03 §3.9.4 守衛設定檔（guard_profile）實際落地登記 SDD 任務書

> **日期**：2026-09-29
> **執行者**：Codex｜**設計、撰寫與審核**：Claude Code
> **基準 commit**：本任務書檔案被加入版控時的那個 commit（見 §7 開頭指示，不寫死 hash）
> **工作目錄**：`D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison`
> **上位文件**：[報告96](96_程式流程與論文03_04登記缺漏盤點.md) §2 A7（「per-KG守衛設定，03§3.9.4只有概念、04無實作說明」）；[報告97](97_專案目標與BT_SM工作流設計.md) §5.3 第 8 項；[報告98](98_論文對齊批次1與5_B2現況與過時狀態修正SDD任務書.md)～[報告101](101_論文對齊批次4_生成流程現況BT圖SDD任務書.md)（已完成並push的結構性重構四批）
> **性質**：**只改一份論文檔案，插入一段說明**。不改程式碼、不改資料、不跑評測、不需要理解程式碼。

---

## 0. 給 Codex 的重點

1. **這是純插入**，不刪除、不改寫任何既有文字——03 §3.9.4 目前只有一段設計說明（描述一個從未真正照該樣子實作的「具名 profile 選擇器」構想），本任務**保留這段原文**，在它後面補一段 ✅ 已實作說明，指出實際落地的形狀跟原設計不同。這是本論文一貫的做法（保留原始設計記錄＋附加實作訂正說明），不是特例。
2. §2 給的文字是**最終版本**，請**逐字複製貼上**，不要自行改寫用詞。
3. 只改一個檔案：`docs/論文/03_系統設計與方法論.md`。另加 03 變更紀錄一筆（共兩個檔案）。
4. 完成後在本機 commit（一個 commit），**不要 push**。

---

## 1. 背景

03 §3.9.4（`### 3.9.4 守衛設定檔（guard_profile）`）目前只有一段文字，描述的是一個**具名 profile 選擇器**的設計構想——用字串如 `"none"`／`"cjk-legal-enumeration"` 選擇一整組預先定義好的守衛 token 清單。

但實際落地（報告76，2026-09-25）的形狀**不是這樣**：Claude Code 已核對程式碼確認，`core/kg_config/model.py::GuardConfig` 是**五個各自獨立的 token 清單欄位**（`measure_units`／`range_trailing_comparators`／`range_leading_comparators`／`scope_modifier_words`／`enum_closed_values`），可以在 domain pack 裡個別覆寫，**沒有**任何具名 profile 字串選擇器；而且目前 `config/domain_packs/taiwan-labor-law.json`／`generic.json` 兩個既有 domain pack 都**沒有**覆寫 `guard` 欄位，完全沿用 shipped defaults，實際運作與改造前一模一樣。

這與 03 §3.1.1 對 `REGIDX` 節點的處理方式（batch2）、§3.2 §b 對檢索順序的處理方式（batch3）是同一類問題：**設計構想與最終實作形狀不同**，需要補一段誠實訂正，而不是假裝原設計就是最終樣貌。

---

## 2. 已定案的內容（Claude Code 設計，請逐字採用）

以下是**完整的插入段落**，插入位置見 §3 T1：

```markdown
> ✅ **已實作（2026-09-25，報告76，取代上方 `guard_profile` 具名 profile 選擇器的原始設計）**：實際落地的形狀比上方設計更簡單——沒有 `guard_profile: "none"`／`cjk-legal-enumeration` 這種具名 profile 選擇器，改為 `KGConfig.guard`（`core/kg_config/model.py::GuardConfig`）直接提供五個 token 清單欄位：`measure_units`（量測單位，供 `_MEASURE_PATTERN`）、`range_trailing_comparators`／`range_leading_comparators`（比較詞，供 `_RANGE_COMPARATOR_PATTERN`）、`scope_modifier_words`（範圍修飾詞，供 `_SCOPE_MODIFIER_PATTERN`）、`enum_closed_values`（封閉列舉值，供 `_ENUM_GUARD_PATTERN`）；中文數字字元類、比較句式間隔長度、序數／分數／小數／附表格式等結構性樣式仍固定在 `services/svo_service.py`，不開放設定。shipped defaults 即目前硬編碼的守衛詞彙（golden test 保證逐字相同），domain pack 可個別覆寫任一欄位；**目前 `taiwan-labor-law`／`generic` 兩個 domain pack 皆未覆寫 `guard`**，實際運作與改造前完全相同，這是架構已就緒、尚待真正客製化第二個語料時才會用到的能力。`svo_service.py::_build_measure_pattern()`／`_build_range_comparator_pattern()`／`_build_enum_guard_pattern()`／`_build_scope_modifier_pattern()` 在 `resolve_entity_name()` 呼叫時把 `_cfg.guard` 組成對應的正則物件。實作範圍屬 RQ4b 實體對齊守衛的設定分層化，不改變任何守衛的判斷邏輯本身（3.4 §b 已實作的模糊合併守衛規則不變）。
```

---

## 3. 任務清單

### T1　03 §3.9.4 插入實作訂正段落

- **檔案**：`docs/論文/03_系統設計與方法論.md`
- **定位**：找到標題 `### 3.9.4 守衛設定檔（guard_profile）`。這個標題下方只有一段文字，以「3.4 的模糊合併守衛正則不再寫死……」開頭，以「……`cjk-legal-enumeration` profile 提供現行勞動法語料所需的完整清單。」結尾；再下一行是空行，接著是下一個標題 `### 3.9.5 逐階段評分閘控的客製化生命週期`。
- **動作**：在這一段的結尾（「……完整清單。」之後）與下一個標題（`### 3.9.5`）之間，插入 §2 給定的完整段落，逐字複製，包含開頭的 `> `。
- **驗證**：插入後，`### 3.9.4` 標題下應該有**兩段**內容——原本的設計段落（一字不動）與新插入的 ✅ 已實作段落；`### 3.9.5` 標題與其後內容維持不動。

### T2　03 變更紀錄

- **檔案**：`docs/論文/03_變更紀錄.md`
- **動作**：依既有格式（參照 2026-09-29 報告101 那筆的寫法）新增一筆 2026-09-29 條目，內容約：「依報告102在 03 §3.9.4 補上守衛設定檔（guard_profile）的實作訂正說明——實際落地（報告76 GuardConfig）是五個獨立 token 清單欄位，不是原設計構想的具名 profile 選擇器，且目前兩個既有 domain pack 皆未覆寫；純新增，未改動原設計段落文字。」

---

## 4. 全域禁止事項

- 不修改任何 `.py`、`.json`、`data/` 檔案；不執行 pytest 或評測。
- 不修改本任務未列出的任何既有文字——本任務是**純插入**，`### 3.9.4` 原本那段設計文字一字不動；`### 3.9.3`、`### 3.9.5` 及其後所有內容一字不動。
- **不得**改寫 §2 給定文字的用詞或語氣。
- 不新增其他小節、不新增圖表。
- 使用繁體中文；沿用既有 blockquote／粗體風格。
- 不 push。

---

## 5. 驗收標準（Claude Code 審核時逐項檢查）

| # | 檢查 | 方法 |
|---|---|---|
| A1 | 新段落逐字插入，位置在 `### 3.9.4` 原段落之後、`### 3.9.5` 標題之前 | 人工核對 §2 文字與插入點 |
| A2 | `### 3.9.4` 原本的設計段落一字未動 | `git diff` 核對（不應出現在刪除行） |
| A3 | `### 3.9.3`、`### 3.9.5` 及其後所有內容一字未動 | 同上 |
| A4 | T2 變更紀錄新增一筆，位置正確 | 人工核對 |
| A5 | `git diff --stat` 只包含 `03_系統設計與方法論.md` 與 `03_變更紀錄.md`，且 `03_系統設計與方法論.md` 只有新增行、沒有刪除行 | `git diff --stat` 與 `git diff` |

---

## 6. 回填區（Codex 填寫）

> 完成後請在這裡填寫，然後 commit。

- **commit SHA**：
- **T1–T2 完成情況**：
- **發現但未處理的其他問題**：

---

## 7. 給 Codex 的指令（使用者可直接貼上）

```text
請在 D:\Users\666\Desktop\world knowledge graph rag\.claude\worktrees\sdd-retrieval-comparison
（分支 worktree-sdd-retrieval-comparison）執行
docs/報告/102_論文對齊_守衛設定檔guard_profile實際落地登記SDD任務書.md。

開始前：
- 先執行 git status 與 git log -1 --oneline，確認 HEAD 為本任務書檔案被加入版控時的那個
  commit（即你現在讀到的這份任務書檔案的來源 commit），且工作區乾淨；
  若工作區不乾淨，或 HEAD 明顯早於這個任務書 commit，先 git pull 或回報實際 HEAD
  後再確認是否繼續，不要用舊版任務書內容做事。

規則：
1. 先完整讀完任務書 §0-§5。§2 給的文字是最終版本，請逐字複製貼上到 §3 指定的位置，
   不要自行改寫用詞。
2. 本任務是純插入，不刪除、不改寫 03_系統設計與方法論.md 中任何既有文字——
   git diff 裡這個檔案應該只有新增行（+），不應該有刪除行（-）。
3. 只改 docs/論文/03_系統設計與方法論.md（T1）與 docs/論文/03_變更紀錄.md（T2）。
   不改任何程式碼、.json、data/ 檔案，不跑 pytest 或評測。
4. 遇到任務書沒涵蓋的情況，記在任務書 §6 回填區，不要自行擴大修改範圍。

完成後：
- 填寫任務書 §6 回填區。
- 自行跑一次 git diff --stat 與 git diff（確認 03_系統設計與方法論.md 只有新增行），
  貼在回報中。
- 全部變更做成一個本機 commit，訊息開頭：docs(論文): 報告102 guard_profile實作訂正
- 不要 push。
- 回報內容：commit SHA、T1-T2 各自完成情況、git diff --stat 的輸出、回填區摘要。
```
