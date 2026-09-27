# 90 報告71殘留4筆`natural_text`法規原文複核與修正SDD任務書（交付Codex）

**建立日期**：2026-09-27
**文件性質**：任務書，交付 Codex 執行，完成後由 Claude Code 複驗。
**觸發脈絡**：報告71（2026-09-23）對KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）96筆`natural_text`型別洩漏做定向backfill，機械品質分級把49筆重算結果分成27筆安全／17筆需人工複核／5筆建議排除；使用者核准backfill這27筆「安全」案例（腳本`scripts/kg/backfill_naturalization_safe_edges.py --apply`）。Claude Code事後逐筆核對這27筆寫入內容，發現機械分級（只檢查「無殘留型別標記」）漏抓4筆有實質內容疑慮的案例，記錄在`data/eval/naturalization_backfill_dryrun_20260923/t2_followup_issues.md`（commit `be17cf0`），當時判定「需要下一輪人工核對法規原文後另案處理」。

**本任務書的直接依據**：Claude Code已用官方「全國法規資料庫」（law.moj.gov.tw）逐條核對這4筆的法規原文，結論跟報告71的機械判斷不一致——**4筆裡有2筆其實是誤判（現在的KG值反而是對的，不需要動），2筆確認需要修正（但其中1筆需要修正的具體位置也跟報告71原本指出的不一樣）**。詳見下方§1。使用者已核准這2筆的修正，本任務書把查證結果與修正動作規格化,交付Codex執行。

---

## 0. 一頁摘要

**目標**：(1) 把Claude Code的法規原文複核結論正式寫進`t2_followup_issues.md`；(2) 對其中2筆確認有問題的Fact，把`natural_text`改成法規逐字對應的正確版本，其餘結構化欄位（subject/verb/object/citations_json等）維持不動；(3) 另外2筆確認是誤判的Fact，不做任何寫入，只在文件中記錄「已複核、維持現狀」。

**範圍**：只動`data/eval/naturalization_backfill_dryrun_20260923/t2_followup_issues.md`（文件更新）與新增一支獨立的一次性腳本（比照`scripts/kg/backfill_naturalization_safe_edges.py`的安全寫入模式），對KG#4的2個relationship執行`SET r.natural_text`。**不改`services/svo_service.py`或任何production抽取/naturalization程式碼**——這是資料層級的手動修正，不是重新設計naturalization邏輯。

**風險控制**：沿用`backfill_naturalization_safe_edges.py`已驗證過的模式——寫入前重新讀取一次現況、跟預期值做compare-and-set guard（含`natural_text`／`subject`／`object`／`citations_json`等欄位全部要吻合才寫，任一欄位跟預期不符就跳過並記錄，不強制覆蓋）、完整寫審計log。

---

## 1. 法規原文複核結果（Claude Code已用law.moj.gov.tw查證，Codex執行前應自行再次確認，不要只憑本節引用文字就直接寫入）

### 1.1 `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:6917546619827179615`（`N0050031_勞工職業災害保險及保護法`第104條）——**誤判，不需修正**

- 目前KG值（`kg_id=236903cf-...`）：`natural_text="勞工保險被保險人於本法施行前已依勞工保險條例規定請領職業災害給付。"`；`subject="勞工保險被保險人"`／`subject_type="PERSON"`／`verb="於本法施行前"`／`object="已依勞工保險條例規定請領職業災害給付"`／`object_type="Action"`。
- **官方條文**（[law.moj.gov.tw](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=N0050031&flno=104)）第104條：
  > 第一項：勞工保險被保險人於本法施行前發生職業災害傷病、失能或死亡保險事故，符合下列情形之一申請補助者，應依本法施行前職業災害勞工保護法規定辦理：一、本法施行前，已依勞工保險條例規定請領職業災害給付。二、依前條第一項規定選擇依勞工保險條例規定請領職業災害給付。
  > 第二項：勞工保險被保險人或受益人依前條第一項規定選擇依本法請領保險給付者，不得依本法施行前職業災害勞工保護法申請補助。
- **結論**：本筆Fact對應第1項第一款「本法施行前，已依勞工保險條例規定請領職業災害給付」，其主詞繼承自第1項前言「勞工保險被保險人」——**第1項全文都沒有「受益人」，「受益人」只出現在語境完全不同的第2項**。報告71當初的T1舊值`"勞工保險被保險人或受益人 PERSON 於本法施行前..."`把「或受益人」誤植進第1項第一款，才是原始抽取的錯誤；naturalization把它拿掉之後，現在的KG值反而跟法條逐字一致。**不需要任何修正**。

### 1.2 `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1155178801978699636`（`N0060088_工程安全設計及整體工程統合管理辦法`第3條）——**誤判，不需修正**

- 目前KG值：`natural_text="其他經中央主管機關指定公告者屬於一定規模以上之工程範圍。"`；`subject="其他經中央主管機關指定公告者"`／`subject_type="概念"`／`verb="屬於"`／`object="一定規模以上之工程範圍"`／`object_type="PLACE"`。
- **官方條文**（[law.moj.gov.tw](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=N0060088&flno=3)）第3條：
  > 本法第十五條之一第一項及第二十七條之一第一項所稱一定規模以上之工程範圍如下：一、應申請建造執照之下列新建建築工程之一：（一）高度達八十公尺以上。（二）開挖深度達十八公尺以上，且開挖面積達五百平方公尺以上。（三）工程造價達新臺幣二億元以上。二、前款以外之工程，其預算金額或契約價金達新臺幣二億元以上。三、**其他經中央主管機關指定公告者**。前項第二款所定工程以分開招標方式辦理者，其金額應合併計算。
- **結論**：第三款逐字就是「其他經中央主管機關指定公告者」，**條文本身完全沒有「高溫作業」這個主詞**。報告71的T1舊值`"其他經中央主管機關指定之高溫作業屬於 PLACE 一定規模以上之工程範圍。"`裡的「高溫作業」本身就是抽取階段的錯誤（可能跟別的chunk混到，例如本KG另一份文件`N0060007_高溫作業勞工作息時間標準`），不是第3條的內容。naturalization拿掉它之後，現在的KG值才跟法條逐字一致。**不需要任何修正**。

### 1.3 `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165041341`（`N0060030_高壓氣體勞工安全規則`第226條）——**確認需要修正**

- 目前KG值：`natural_text="發生災害時之 災害原因調查及檢討防災對策 左列高壓氣體製造安全有關事項"`；`subject="發生災害時之"`／`subject_type="Action"`／`verb="災害原因調查及檢討防災對策"`／`object="左列高壓氣體製造安全有關事項"`／`object_type="WORK_GUIDELINE"`；`citations_json`來源`N0060030`第226條。
- **官方條文**（[law.moj.gov.tw](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=N0060030&flno=226)）第226條（前言＋七款列舉）：
  > 前條之製造安全規劃人員，輔導製造安全負責人規劃左列高壓氣體製造安全有關事項：一、規劃訂定有關高壓氣體製造安全工作守則。二、規劃安全教育計畫並予推展。三、前二款規定外，有關製造安全之基本對策。四、提供有關製造安全之作業標準、設備管理基準或承攬管理及發生災害或防範發生災害之措施基準之建議並實施指導等。五、規劃防災訓練及推展。六、**發生災害時之災害原因調查及檢討防災對策**。七、蒐集有關製造高壓氣體之資料。
- **結論**：本筆Fact對應第六款，逐字就是「發生災害時之災害原因調查及檢討防災對策」。目前KG的`object`欄位「左列高壓氣體製造安全有關事項」其實是**前言（stem）的文字**，不屬於第六款本身——抽取階段把前言誤併進第六款的三元組，naturalization忠實地把subject+verb+object三段都render出來，才造成語序破碎的結果。**這是真正的內容問題，需要修正`natural_text`**；修正只動`natural_text`字串本身，不動`subject`/`verb`/`object`欄位（結構化欄位的前言誤併是另一個更深層的抽取問題，不在本任務書範圍內，見§4）。
- **修正目標**：`natural_text` 改為法條逐字：**`發生災害時之災害原因調查及檢討防災對策。`**（句尾補句號，跟其餘27筆已backfill案例的風格一致）。

### 1.4 `5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152937997281292486`（`N0090002_私立就業服務機構許可及管理辦法`第3條）——**確認需要修正，但問題點跟報告71原判斷不同**

- 目前KG值：`natural_text="接受從事本法第四十六條規定工作之外國人委任 代其辦理居留業務 始得從事就業服務業務"`；`subject="接受從事本法第四十六條規定工作之外國人委任"`／`subject_type="ORGANIZATION"`／`verb="代其辦理居留業務"`／`object="始得從事就業服務業務"`／`object_type="Service"`；`citations_json`來源`N0090002`第3條。
- **官方條文**（[law.moj.gov.tw](https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=N0090002)）第3條第三款：
  > 三、接受從事本法第四十六條第一項第八款至第十一款規定工作之外國人委任，**代其辦理居留業務**。
- **結論**：報告71原本懷疑「代其辦理居留業務」是LLM加料——**這句其實是對的，逐字對應第三款**。真正查無出處的是`object`欄位／`natural_text`尾段的**「始得從事就業服務業務」**——Claude Code查過第3條全文與第13條全文（`https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=N0090002`、`https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=N0090002&flno=13`），都找不到這句話的出處，且T1舊值（`"ORGANIZATION接受從事本法第四十六條規定工作之外國人委任代其辦理就業服務業務。"`）裡也沒有這句話——它是後來才出現的內容，來源不明，**目前證據下應視為抽取或naturalization過程中混入的可疑內容**。
- **修正目標**：`natural_text` 改為只保留已驗證的部分：**`接受從事本法第四十六條規定工作之外國人委任，代其辦理居留業務。`**（同樣只動`natural_text`；`object`欄位「始得從事就業服務業務」的來源問題不在本任務書範圍內，見§4）。
- **⚠️ Codex執行前務必再次確認**：這是本任務書4筆結論裡查證強度最弱的一筆（「查無出處」是排除法，不是找到反證），若Codex有能力再次核對，應優先確認官方法規全文（含所有款次與可能的第2項）裡是否真的完全沒有這句話；若Codex查到不同結果，應如實回報並暫緩寫入，而不是照抄本任務書執行。

---

## 2. 設計

### 2.1 新增獨立腳本 `scripts/kg/fix_report90_verified_naturalization_facts.py`

**不要**修改或重用`scripts/kg/backfill_naturalization_safe_edges.py`本身（那支腳本的`SAFE_EDGE_SUFFIXES`與`t2_write_log.json`是27筆批次的固定審計紀錄，混用會污染既有審計軌跡）。新腳本比照同一套安全模式，但只處理本任務書§1.3/§1.4這2筆：

```python
KG_ID = "236903cf-055a-40a8-8923-b9d06601f3b7"
TARGETS = {
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165041341": {
        "rel_type": "RELATED_TO",
        "subject": "發生災害時之",
        "subject_type": "Action",
        "object": "左列高壓氣體製造安全有關事項",
        "object_type": "WORK_GUIDELINE",
        "expected_old": "發生災害時之 災害原因調查及檢討防災對策 左列高壓氣體製造安全有關事項",
        "new_text": "發生災害時之災害原因調查及檢討防災對策。",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152937997281292486": {
        "rel_type": "USED_FOR",
        "subject": "接受從事本法第四十六條規定工作之外國人委任",
        "subject_type": "ORGANIZATION",
        "object": "始得從事就業服務業務",
        "object_type": "Service",
        "expected_old": "接受從事本法第四十六條規定工作之外國人委任 代其辦理居留業務 始得從事就業服務業務",
        "new_text": "接受從事本法第四十六條規定工作之外國人委任，代其辦理居留業務。",
    },
}
```

其餘結構（讀取查詢、compare-and-set寫入查詢、preflight/`--apply`模式、審計log）**逐一比照**`backfill_naturalization_safe_edges.py`的`READ_QUERY`／`WRITE_QUERY`／`apply_one()`／`run()`寫法，包括：
- 預設preflight（不帶`--apply`）只印出每筆現況是否跟`expected_old`／`subject`／`subject_type`／`object`／`object_type`／`kg_id`吻合（`READY`／`SKIP <diffs>`），不執行任何`SET`。
- `--apply`模式：對每筆重新讀取現況，若`natural_text`／`subject`／`subject_type`／`object`／`object_type`／`kg_id`任一與`TARGETS`不符就跳過（`skipped_source_changed`），一致才執行`SET r.natural_text = $new_text`（用compare-and-set guard，不是無條件覆蓋）。
- 審計log寫到新路徑：`data/eval/naturalization_backfill_dryrun_20260923/report90_manual_fix_write_log.json`（沿用同一個資料夾延續脈絡，但檔名區分開，不覆寫既有的`t2_write_log.json`）。
- `citations_json`欄位**不**作為這次的guard條件（本任務書的2筆修正不需要比對citations_json；若要加上也可以，但不是必要條件，比照風格取捨即可，重點是`natural_text`/`subject`/`object`等內容欄位要吻合）。

### 2.2 `t2_followup_issues.md`更新

在檔案末尾新增一節「## 2026-09-27 法規原文複核結論與修正結果」，內容依§1的4筆逐一記錄結論（誤判/需修正），修正的2筆額外記錄修正後的`natural_text`與腳本`--apply`執行後的`status`（`written_verified`/`skipped_*`/`failed`）。

---

## 3. 任務清單

### T1（S）：`t2_followup_issues.md`新增複核結論章節

- 依§2.2把本任務書§1的4筆結論（含官方條文引用、URL、判定理由）整理進文件新章節。此步驟只是文件記錄，不涉及程式或資料庫。

### T2（M）：新增`fix_report90_verified_naturalization_facts.py`並跑preflight

- 依§2.1實作。跑一次不帶`--apply`的preflight，確認2筆都印出`READY`（現況跟§1記錄的`expected_old`/`subject`/`object`等欄位吻合，沒有drift）。**若preflight印出`SKIP`（欄位不吻合），停下來回報現況與本任務書記錄的差異，不要略過guard直接改腳本去配合現況**——這代表KG狀態在2026-09-23之後又被別的操作動過，需要使用者確認要不要用新現況重新走一次法規複核，而不是直接假設本任務書的判斷仍然適用。

### T3（S）：執行`--apply`並驗證

- preflight確認`READY`後，執行`--apply`，確認2筆都是`written_verified`。跑完後各自用一次獨立的read-only Cypher查詢（例如`MATCH ()-[r]->() WHERE elementId(r)=$edge_id RETURN r.natural_text`）覆核，確認`natural_text`已更新為§1.3/§1.4記錄的目標值。

### T4（S）：`t2_followup_issues.md`補上執行結果＋pytest

- 在T1新增的章節裡補上T3的執行結果（`written_verified`或例外狀況）與`report90_manual_fix_write_log.json`路徑。跑`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`確認沒有因為新增腳本或既有測試受影響（新腳本本身是一次性資料修正工具，不需要新增單元測試，比照`backfill_naturalization_safe_edges.py`沒有對應pytest的先例）。

---

## 4. 明確不做的事

- **不修改`services/svo_service.py`或任何production抽取/naturalization程式碼**——本任務書是針對已寫入KG#4的2筆Fact做資料層級手動修正，不是重新設計抽取或naturalization邏輯。
- **不修改`subject`/`verb`/`object`等結構化欄位**——即使§1.3/§1.4都指出這些欄位本身可能混入了前言/來源不明的內容（這是比naturalization更深一層的抽取問題），本任務書的範圍只修`natural_text`字串，結構化欄位的問題留給未來另立任務處理，不在本次順手修掉。
- **不動`t2_write_log.json`或`SAFE_EDGE_SUFFIXES`**——那是27筆批次的既有審計紀錄，新腳本用獨立的log檔案。
- **不處理報告71殘留的17筆需人工複核、5筆建議排除案例**——本任務書只處理這4筆（其中2筆確認需修正）,其餘案例不在範圍內、不要自動擴大處理。
- **不需要對其他KG做同樣的複核**——本任務書只針對KG#4這2筆已知案例。

---

## 5. 驗收標準

1. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠。
2. Preflight模式對2筆的guard比對如實印出結果，若有drift要停下回報而非強行套用。
3. `--apply`後2筆的`natural_text`經獨立read-only查詢覆核確實等於§1.3/§1.4的目標值。
4. `t2_followup_issues.md`完整記錄複核結論（4筆，含2筆誤判、2筆修正）與最終執行狀態。
5. `git diff --stat`只涉及：新腳本1個、`t2_followup_issues.md`、新的`report90_manual_fix_write_log.json`（若腳本執行產生）。不涉及`services/`、`routers/`、`core/`任何production程式碼。

---

## 6. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/90_報告71殘留4筆natural_text法規原文複核與修正SDD任務書.md` 的 T1-T4。
>
> 背景：報告71對KG#4（`236903cf-055a-40a8-8923-b9d06601f3b7`）做過96筆`natural_text`型別洩漏backfill，27筆已核准寫入（`scripts/kg/backfill_naturalization_safe_edges.py`）。Claude Code事後逐筆核對，發現其中4筆有內容疑慮，記錄在`data/eval/naturalization_backfill_dryrun_20260923/t2_followup_issues.md`。這次Claude Code已用官方「全國法規資料庫」（law.moj.gov.tw）逐條核對這4筆的法規原文，結論是**2筆其實是誤判（現況已經是對的，不用修）、2筆確認需要修正**——任務書§1有完整的官方條文引用、URL與判定理由，請先讀過。
>
> **T1**：把§1的4筆複核結論（含官方條文引用）整理進`t2_followup_issues.md`新章節「## 2026-09-27 法規原文複核結論與修正結果」。
>
> **T2**：依§2.1新增獨立腳本`scripts/kg/fix_report90_verified_naturalization_facts.py`（**不要**改動或重用既有的`backfill_naturalization_safe_edges.py`，那是27筆批次的既有審計工具），只處理§1.3（`1152927002165041341`）與§1.4（`1152937997281292486`）這2個edge_id，比照`backfill_naturalization_safe_edges.py`的preflight/`--apply`/compare-and-set寫入guard/審計log模式（審計log寫到新檔案`data/eval/naturalization_backfill_dryrun_20260923/report90_manual_fix_write_log.json`）。先跑一次不帶`--apply`的preflight，確認2筆都是`READY`（現況跟任務書§2.1的`expected_old`/`subject`/`object`欄位吻合）——**如果有任何一筆是`SKIP`，停下來回報差異，不要自行調整guard去配合現況，等待進一步指示**。
>
> **T3**：preflight確認`READY`後執行`--apply`，確認2筆都是`written_verified`，並各自用一次獨立read-only查詢覆核`natural_text`確實已更新為任務書§1.3/§1.4指定的目標值。
>
> **T4**：把T3的執行結果補進T1新增的章節，跑`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`確認全綠。
>
> **範圍限定**：全程**不要**修改`services/svo_service.py`或任何production程式碼，**不要**動`subject`/`verb`/`object`等結構化欄位（即使發現這些欄位本身也有問題，只記錄不修正），**不要**處理報告71殘留的17筆需複核／5筆建議排除案例，**不要**動既有的`t2_write_log.json`或`SAFE_EDGE_SUFFIXES`。§1.4（居留業務案）的查證強度較弱（「查無出處」是排除法），若你有能力再次核對法規全文且發現與任務書不同的結果，請如實回報並暫緩該筆寫入，不要照抄任務書執行。commit前不需要額外詢問，但push需要使用者另行同意。
