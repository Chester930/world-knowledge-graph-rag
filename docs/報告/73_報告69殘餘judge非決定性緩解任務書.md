# 73 報告69殘餘judge推論非決定性緩解任務書（交付Codex）

**建立日期**：2026-09-23
**文件性質**：任務書，交付 Codex 執行，完成後由 Claude Code 複驗。
**觸發脈絡**：[報告69](69_評測harness固定metric-judge與受測arm-judge解耦SDD任務書.md)T5驗證確認固定metric-judge能消除「換受測judge污染Stage1-4量測分數」的confound（7題中5題完全一致，比修法前3/7進步），但殘餘2題（`57-CANARY5`／`57-AGGR19`）仍不一致。獨立查證（見[HANDOVER.md](../../HANDOVER.md)「2026-09-23 報告69」段落）確認根因是**同一個固定metric-judge對同一段文字、同一個gold span做語意蘊含核對，兩次呼叫給出不同true/false判斷**——`core/providers/llm/ollama.py`已設`temperature=0.0`＋固定`seed`，但程式碼註解本身誠實聲明無法完全消除（batch size依賴的浮點運算非結合律，與報告20已引用的Horace He/Thinking Machines Lab機制同源），**不是報告69這次修法的缺陷**。

---

## 0. 一頁摘要

**目標**：針對HANDOVER記錄的3個待裁選項中的(b)(c)——設計並評估「語意fallback核對多次取眾數」這個緩解方案是否值得採用，並用有緩解後的結果重新評估「乾淨樣本是否足以支撐獨立judge是否有效」這個結論。**(a)是否push `1f353d8`已經解決**（已確認本分支`git status`只剩今天的HANDOVER文件commit未push，`1f353d8`本身已推送）。

**設計原則**：比照專案既有的`scripts/eval/adaptive_repeat.py`「品質門檻式規則」精神——多次執行取眾數是已經在本專案驗證過的緩解模式，不是新發明的機制，但這次應用在**單次語意核對呼叫**而非整題重跑，成本結構不同，需要謹慎評估。

---

## 1. 現況（已查證，供直接引用）

1. **確定性殘餘根因**：`services/semantic_span_matcher.py::match_spans_with_fallback()`在逐字比對失敗時呼叫`judge_llm_provider`做語意蘊含核對；`core/providers/llm/ollama.py`第35-57行`OllamaLLMProvider`已設`temperature=0.0`＋固定seed，但這無法完全消除batch-size依賴的浮點非結合律導致的輸出變動。
2. **報告20已有類似先例**：抽取階段的非決定性緩解措施設計與取捨，本任務書應參考同樣的成本效益判斷框架（不是無條件套用多次呼叫，需衡量呼叫成本增加）。
3. **`adaptive_repeat.py`既有模式**：品質門檻式規則——達標即停、無法判定才補跑，最多3次，抽查約25%單次通過案例。這是「整題重跑取眾數」的既有實作，本任務書的新機制是「單次語意核對呼叫內部多次取眾數」，粒度更細、呼叫成本更低（只重跑judge的一次`generate_json()`呼叫，不需要重跑整個生成+檢索流程）。
4. **殘餘不一致的2個案例特性**：`57-CANARY5`（Stage1 Recall 1.0→0.5）、`57-AGGR19`（0.25→0.5，且`57-AGGR19`本身是報告62 §14.11已知的「限定條件遺失」邊界案例，語意判斷本就落在模糊邊界）——後者即使緩解了推論非決定性，語意本身的模糊性仍可能導致眾數判斷不穩定，這是設計T1/T2時要留意的預期落差。

---

## 2. 任務清單

### T1（S，設計＋實作）：語意fallback核對的多數決緩解機制

- 在`services/semantic_span_matcher.py::match_spans_with_fallback()`新增選填參數（例如`semantic_fallback_repeats: int = 1`），當`>1`時對同一組(答案片段, gold span)語意蘊含核對呼叫judge **N次**（例如3次），取多數決（true/false哪個出現次數多），並保留每次個別呼叫的原始判斷結果（寫入評測harness的lineage/trace，供事後稽核判斷是否穩定或本身就在1:1:1這種無多數的邊界情況——若發生這種情況，設計上採保守策略：判定不穩定時退回`false`（missing），並在紀錄中明確標注「judge多數決無法收斂」，不要靜默選一個）。
- 這個參數**只在harness評測層可用**（透過`AtomicScorer`/`tracker`的呼叫鏈傳入），**不要修改`chat()`正式生成路徑的判斷邏輯**——正式`chat()`內部重生成決策目前用單次呼叫，這是production行為，不在本任務書調整範圍。
- **預設不啟用**（`semantic_fallback_repeats=1`時行為與現況逐字相同，golden-test精神比照報告66/68/69先例）。
- 新增單元測試：涵蓋N=1時行為不變、N=3時多數決正確運作、1:1:1不收斂時的保守退回邏輯、每次個別呼叫結果確實被記錄。

### T2（S，驗證）：用報告69 T5同一批題重跑，觀察殘餘不一致是否改善

- 用報告69 T5的同一批7題（`.claude/tmp/report65_targeted_karm_20260922/questions.json`）與同一份embedding快取，固定`--metric-judge-provider ollama --metric-judge-model qwen2.5:7b`，這次額外啟用`semantic_fallback_repeats=3`，各跑一次共用judge臂與獨立judge臂。
- **驗收重點**：`57-CANARY5`／`57-AGGR19`這2題的Stage1 Recall是否變得一致。**如實回報**——即使緩解機制正確實作，`57-AGGR19`本身的語意模糊性質仍可能導致不穩定（見§1.4），這不代表T1實作有誤，需要在回報中區分「機制沒生效」與「語意本身邊界模糊、多數決也救不回」兩種情況。
- 輸出到新路徑（例如`.claude/tmp/report73_semantic_repeat_20260923/`），不要覆寫`report68_embedding_cache_20260922`／`report69_metric_judge_fixed_20260922`下的既有資料夾。

### T3（S，決策彙整，非執行）：是否正式重跑獨立judge pilot——彙整證據供使用者裁示

- 不需要自行決定要不要做，但需要把判斷所需的證據整理清楚：
  - T2完成後，乾淨樣本（Stage1 Recall在共用judge臂與獨立judge臂之間完全一致的題數）從報告69的5/7變成多少（T2結果）。
  - 若T2後仍有殘餘不一致，评估這是否代表：即使有緩解機制，n=7的pilot規模仍然不足以可靠判斷「獨立judge是否改善結果」（因為單題的judge非決定性雜訊幅度可能跟預期的judge效應量同一個數量級）。
  - 在報告中列出2-3個選項供使用者裁示，例如：(i) 現有7/7或接近全部一致，可以考慮正式擴大到42題凍結基準規模跑一次獨立judge pilot；(ii) 仍有殘餘雜訊，建議先接受「小規模pilot不足以下定論」，暫緩獨立judge pilot，把資源優先放在報告72的S0-S3；(iii) 其他方案（例如只挑`57-CANARY5`/`57-AGGR19`這類已知邊界題外的題目子集做pilot，繞開已知的判斷模糊案例）。
  - **不要在本任務書內擅自決定要不要跑42題規模的正式pilot**——那是需要使用者權衡成本（Ollama長時間佔用、42題×多次repeat的呼叫量）後裁示的事。

---

## 3. 明確不做的事

- **不修改`routers/agent.py::chat()`正式生成路徑的判斷邏輯**——`semantic_fallback_repeats`只在評測harness層可用。
- **不修改`AtomicScorer`或其他Stage1-4評分邏輯本身**——只在`match_spans_with_fallback()`內部的judge呼叫次數上做文章，評分規則不變。
- **不自動執行42題規模的正式獨立judge pilot**——T3只彙整證據，實際要不要跑、規模多大，需要使用者裁示。
- **不把`semantic_fallback_repeats`預設值改成大於1**——維持opt-in，預設行為零變化。
- **不重新論斷`57-AGGR19`的判定結果本身**——報告62 §14.11已裁決该題「推翻原判改判不支持」，本任務書不重新開放這個裁決，只處理judge推論穩定性這個獨立議題。

---

## 4. 驗收標準

1. T1的多數決機制有單元測試覆蓋，且N=1時行為與現況逐字相同。
2. T2的結果誠實回報（無論殘餘不一致是否改善），並區分「機制生效與否」跟「案例本身語意模糊」兩種可能。
3. T3提供的選項清單具體、可執行，不是空泛的「請使用者決定」，而是附帶足夠的證據與取捨供裁示。
4. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`全綠。

---

## 5. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/73_報告69殘餘judge非決定性緩解任務書.md` 的T1-T3。背景：報告69已用固定metric-judge消除「換受測judge污染Stage1-4量測分數」的confound（7題中5題完全一致，比修法前3/7進步），但殘餘2題（`57-CANARY5`／`57-AGGR19`）仍不一致，獨立查證確認根因是同一個固定metric-judge對同一段文字做語意蘊含核對時，兩次呼叫給出不同true/false判斷（`core/providers/llm/ollama.py`固定seed無法完全消除batch-size依賴的浮點非結合律，與報告20同源機制），不是程式邏輯缺陷。**T1**：在`services/semantic_span_matcher.py::match_spans_with_fallback()`新增選填參數`semantic_fallback_repeats: int = 1`（預設1時行為與現況逐字相同），`>1`時對同一組核對呼叫judge N次取多數決，1:1:1不收斂時保守退回`false`並在紀錄中明確標注「judge多數決無法收斂」，每次個別呼叫結果需保留供稽核。**只在評測harness層可用，不要修改`chat()`正式生成路徑的判斷邏輯**。新增單元測試涵蓋N=1不變、N=3多數決、不收斂情境、個別呼叫記錄。**T2**：用報告69 T5同一批7題（`.claude/tmp/report65_targeted_karm_20260922/questions.json`）與同一份embedding快取，固定`--metric-judge-provider ollama --metric-judge-model qwen2.5:7b`，啟用`semantic_fallback_repeats=3`各跑一次共用judge臂與獨立judge臂，輸出到新路徑`.claude/tmp/report73_semantic_repeat_20260923/`（不要覆寫既有的report68/69資料夾），檢查`57-CANARY5`／`57-AGGR19`是否變得一致，如實回報（區分「機制沒生效」與「語意本身邊界模糊、多數決也救不回」）。**T3**：不要自行決定要不要正式擴大到42題規模跑獨立judge pilot，而是彙整T2後的乾淨樣本比例變化，列出2-3個具體選項（例如維持現狀評估、擴大到42題正式pilot、排除已知邊界題的子集pilot）供使用者裁示，附帶足夠證據與成本取捨（Ollama長時間佔用、呼叫量增加）。全程開工前用ListAgents確認沒有其他Claude session在用同一組Neo4j/Ollama，唯讀不寫KG。完成後跑`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`確認全綠並回報結果。
