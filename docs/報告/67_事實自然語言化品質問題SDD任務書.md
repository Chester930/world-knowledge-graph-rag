# 67 事實自然語言化（natural_text）品質問題SDD任務書

**建立日期**：2026-09-22
**文件性質**：診斷＋任務書。**本報告內容尚未實作**，是報告65 §10「另開任務處理」的落地——報告65處理的是三元組拆解粒度（抽取端），本報告處理的是**已抽取三元組改寫成自然語句**（`services/svo_service.py::_naturalize_triple()`，報告24機制）本身的生成品質，兩者是不同的函式、不同的問題層次，不要混在一起改。
**分支／工作區**：`worktree-sdd-retrieval-comparison`
**觸發脈絡**：報告65 §10 全KG規模驗證（掃描10,531筆BFS-Fact碰撞、7,338筆文字有實質差異）過程中，意外發現 `natural_text`（BFS三元組顯示時優先使用，見`_split_fact_lines()`）存在兩類尚未被任何既有機制擋下的資料品質問題。

---

## 0. 一頁摘要

**問題**：`_naturalize_triple()` 把三元組改寫成自然語句時，LLM 有時會（a）把 prompt 裡當作輔助資訊送入的「（型別）」標記**原樣或變形地**洩漏進輸出，且不符合既有防禦性清除的正則格式；（b）疑似把不同 citation 的內容改寫混淆成同一句。這兩個問題都是**在 LLM 改寫路徑本身發生**，不是報告25已記錄的「殘缺三元組跳過LLM、用樣板兜底」那個舊問題（見§2「與既有已知問題的關係」）。

**已查證的根因**（不是猜測）：`_naturalize_triple()`（`services/svo_service.py:1740`）把型別資訊用 `f"{subject}（{subject_type}）"` 的形式直接嵌進送給 LLM 的 prompt（第1782-1784行），要求 LLM 改寫成自然語句，但**prompt 沒有明確指示「型別標記只是輔助資訊、不可以照抄進輸出」**，也**沒有任何核對步驟檢查輸出是否還殘留型別標記**（既有的 `_naturalization_dropped_quantity()` 只核對「遺漏」方向，沒有核對「殘留/新增不該有的字面內容」方向）。`routers/agent.py::_TYPE_MARKER_RE`（`r"\s*（(?:概念|[A-Za-z][A-Za-z0-9_]*)）"`）這道輸出前防禦性清除**只吃「單一型別詞＋全形括號」這一種格式**，抓不到裸露無括號的 `ORGANIZATION`、或逗號分隔的 `（PERSON,PERSON,PERSON,PERSON）` 這類變形——已用真實字串驗證這個正則確實不會匹配這些案例。

**規模**：報告65 §10 的全KG掃描（KG#4，`236903cf-055a-40a8-8923-b9d06601f3b7`）裡，7,338筆BFS-Fact文字有差異的碰撞案例中抽樣審視即發現多筆型別洩漏與疑似內容錯置，不是單一孤例。

---

## 1. 已查證的兩類問題（真實案例，來自報告65 §10掃描）

### 1.1 型別標記字面洩漏（未被 `_TYPE_MARKER_RE` 擋下）

| subject | 洩漏後的 `natural_text` | 說明 |
|---|---|---|
| 本辦法 | `'本辦法所稱定團體是指ORGANIZATION。'` | 裸露無括號的型別詞，`_TYPE_MARKER_RE` 要求全形括號包住，抓不到 |
| 最高負責人 | `'最高負責人 POSITION 確定地方主管機關應依下列各款規定審認之 ORGANIZATION。'` | 兩處型別詞洩漏，且句子本身也不通順（疑似改寫失敗） |
| 因離婚或其配偶死亡致婚姻關係消滅後 | `'因離婚或其配偶死亡致婚姻關係消滅後依法准予繼續居留者（PERSON,PERSON,PERSON,PERSON）。'` | 有全形括號，但內容是逗號分隔的重複型別詞列表，不符合 `_TYPE_MARKER_RE` 要求的「單一型別詞」格式 |

### 1.2 疑似內容錯置

| 案例 | 說明 |
|---|---|
| `subject='保險人' object='辦理業務使用之醫療藥品與器材'` | `natural_text` 是 `'保險人辦理業務使用之治療救護車輛得以免徵稅捐。'`——講的是**另一筆**（`object='辦理業務使用之治療救護車輛'`）事實的內容，兩筆不同的Fact卻共用同一句 `natural_text` |
| `subject='雇主' verb='僱用' object='勞工'` | `fact_text`（三元組本身）語意是「雇主僱用勞工」，對應的 `natural_text` 卻是「僱主應依勞動基準法之規定，發給勞工。」——主題不同，疑似跟另一筆citation混淆 |

**尚未查明**這是 `_naturalize_triple()` 本身的LLM生成錯誤，還是 `merge_triples_to_graph()` 累積 citation 時 `natural_text` 覆蓋邏輯（"每次有新citation合併時都重新生成、覆蓋舊值"）有時序或參數傳遞上的bug——這是本任務書 §3 T1 要優先釐清的問題。

---

## 2. 與既有已知問題的關係（避免重複研究）

`docs/報告/25_擴大版新舊KG問答品質比對報告.md` §5 第5點**已經記錄過**類似現象（「佔位符洩漏仍在（題1[B]、題4[A][B]）：`（PLACE）`、`（PERSON）`、`（PRODUCT）`、`（概念）` 進到最終答案」），但**根因不同**：報告25 當時定位的根因是「報告24 階段4『殘缺三元組跳過LLM改寫』的決策，代價是這些被跳過的關係保留了 `_verbalize_fact()` 樣板拼接的 `（型別）` 標記」——也就是**觸發條件是三元組不完整（缺subject/object），根本沒呼叫LLM**。

**本報告發現的是不同的觸發路徑**：§1的案例三元組本身完整（subject/verb/object都有內容），**確實有呼叫LLM改寫**，但LLM輸出本身就帶著洩漏或錯置——這代表報告25的舊發現＋本報告的新發現，合起來至少是**兩條獨立的洩漏路徑**，不是同一個根因的不同症狀。修報告25那條路徑（例如判斷完整性後才呼叫LLM，或完整性判斷本身更嚴謹）不會自動修好本報告發現的這條路徑。

---

## 3. 任務清單（交付 Codex，依序執行；T1結論決定T2-T4的實際寫法）

### T1（S，先做，唯讀，不動KG資料）：釐清根因——LLM輸出問題還是寫入時序問題

**背景查證**（已確認，寫入這裡供直接引用，不必重查）：`merge_triples_to_graph()`（`services/svo_service.py:1953`起）對每個 `SVOTriple` 循序 `await`（無 `asyncio.gather`），單次呼叫內部沒有並發寫入同一條邊的風險；但**跨呼叫**（例如同一份文件的不同chunk、或不同chunk由不同worker並發抽取，各自命中同一條`(subject,rel_type,object)`邊）屬於典型 read-modify-write race：兩次呼叫都在 `MERGE...RETURN r.citations_json`（第1962-1973行）讀到同一份舊值，各自附加自己的citation後回寫，後寫的會覆蓋先寫的——`natural_text`（第2010-2015行）同樣是「這次呼叫算出的值直接SET覆蓋」，沒有任何版本檢查。**這個race本身足以同時解釋型別洩漏（某次呼叫的LLM輸出剛好沒處理好型別標記）與內容錯置（後寫入的natural_text描述的是另一個citation的verb，但citations_json本身沒有race、只是natural_text跟citations_json不是同一個原子寫入）兩種症狀，值得優先排除。**

1. **唯讀查詢**（沿用報告65已寫過的模式）：從 KG#4 抓出報告65 §10 §1.1/§1.2 列出的具體案例，讀出對應邊的完整 `citations_json`（不只是最新一筆），核對：`natural_text` 描述的內容，是否對應 `citations_json` 裡**任何一筆**（不一定是最後一筆）citation 的 `verb`/`source_svo_chunk_index`。如果對應到「非最後一筆」，強烈支持race假說。
2. **重現嘗試**：用查到的 `subject`／`subject_type`／`verb`／`object`／`object_type`（從對應的 citation 或 Fact 節點取得），直接呼叫 `_naturalize_triple()`（同樣的 llm_provider，`OLLAMA_LLM_THINK` 等環境變數比照報告62 §7），跑 3-5 次，記錄是否重現型別洩漏。**能穩定重現 → LLM/prompt 問題（進T2/T3）；完全不重現 → 傾向race假說（進T1b，設計方案時另案討論，不在本任務書自動展開，因為修並發寫入需要動 `merge_triples_to_graph()` 的交易/鎖設計，範圍比T2/T3大得多，要先讓使用者看過T1結果再決定要不要做）**。
3. **產出**：把查詢結果與重現測試結果整理成一段文字（不需要正式報告格式），附在 commit message 或本報告§1.3（新增小節），讓後續者一眼看懂結論是哪一種。

### T2（S，需T1判定為「LLM/prompt問題」才做）：prompt 補強＋新增輸出核對（型別洩漏方向）

- 比照 `_naturalization_dropped_quantity()`（`services/svo_service.py:1720`，核對「遺漏」方向）的既有架構，新增鏡像函式（建議命名 `_naturalization_leaked_type_marker()`）核對「殘留不該有的型別標記」方向：直接核對 `subject_type`／`object_type`（非空時）的型別詞字串本身，是否以任何形式（含裸字、逗號列表）出現在 `natural_text` 輸出裡。
- `_naturalize_triple()`（第1740行）命中 `_naturalization_leaked_type_marker()` 時，比照既有 `_naturalization_dropped_quantity()` 的既有回傳邏輯（第1789-1791行），退回 `_verbalize_fact()` 樣板拼接——**不要另外發明新的降級路徑**，兩種核對失敗都收斂到同一個 fallback。
- `_NATURALIZE_PROMPT_TEMPLATE`（第1711-1717行）補一句明確指示：型別標記只是輔助語意判斷用，不可以把型別名稱本身（PERSON、ORGANIZATION 等英文字）照抄進輸出。
- 新增單元測試：至少涵蓋「裸字洩漏」「逗號列表洩漏」「型別標記在合法語意詞彙中出現但非洩漏（例如型別詞剛好是常見英文縮寫、但語境正常）」三種情境，避免過度攔截。

### T3（S，可與T2平行）：`_TYPE_MARKER_RE` 補強成防禦性最後一道防線

- `routers/agent.py::_TYPE_MARKER_RE`（約行547）目前只吃「單一型別詞＋全形括號」。即使 T2 的核對機制生效，這道「輸出前清除」防線的格式覆蓋率也該補強，不依賴 T2 一定攔下（雙重防護，T2失敗有第二道防線）。
- **風險（務必遵守）**：型別詞若跟合法中文語意重疊，過度寬鬆的正則可能誤刪合法內容——**必須用 `core/constants.py` 既有的受控型別清單逐詞比對，不能用寬鬆萬用正則去匹配任意大寫英文字**（否則可能誤刪句子裡合法出現的英文縮寫，例如法規條文本身引用的英文機構縮寫）。
- 新增單元測試涵蓋：裸字型別詞清除、逗號列表型別詞清除、合法英文縮寫（不在受控型別清單裡的）不被誤刪。

### T4（M，**只產出估算報告，不執行backfill**）：既有KG資料受影響範圍估算

- 寫一支唯讀腳本，對全KG（或至少報告65 §10已掃描過的KG#4）套用T2的核對邏輯（`_naturalization_leaked_type_marker()`），統計目前有多少筆邊的 `natural_text` 已經受影響。
- **只回報統計數字與樣本，不要執行任何 backfill 寫入**——backfill 是不可逆的KG資料異動，範圍與必要性需要使用者看過T1-T3的結果與T4的統計後才能決定，不在本任務書自動核准的範圍內。

---

## 4. 明確不做的事

- 不在本任務內動報告65的規則10或`prefer_fact_on_collision`旗標——那是抽取粒度問題，本報告是自然語言化生成品質問題，兩者無關。
- 不假設T1一定能查出根因——若T1查完仍無法重現或定位，誠實記錄「查無法穩定重現，暫列為已知瑕疵」，不要為了交差硬套一個沒驗證過的解釋；此時T2/T3也不要動手，回報結果即可。
- **T4只做估算，絕對不執行backfill**——這是不可逆的KG資料異動。
- 不修 `merge_triples_to_graph()` 的並發寫入race（若T1support這個假說）——那是另一個範圍更大的任務，本任務書只負責診斷出這個可能性並回報，不在此展開修復設計。

---

## 5. 驗收標準

1. T1的查詢結果與重現測試結論，清楚寫成文字（附在commit message或本報告新增小節），讓人不需要重跑就能知道結論是「LLM/prompt問題」還是「race問題」還是「無法判定」。
2. 若做了T2/T3：`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠，新增測試數量要反映實際新增的核對邏輯，不是形式湊數。
3. 若做了T4：只有一份統計/樣本報告，`git status` 確認沒有任何 Neo4j 寫入操作被執行（本任務書範圍內的程式碼只有讀查詢）。
4. commit前不需要額外詢問使用者，但commit message要清楚交代T1的判定結果，讓下一個接手的人（含我，負責驗證）不必重新调查一次。

---

## 6. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/67_事實自然語言化品質問題SDD任務書.md` 的 T1，**先只做T1，不要自動接著做T2/T3/T4**。T1 是唯讀調查：釐清報告65 §10 發現的 `natural_text` 型別標記洩漏／疑似內容錯置，根因是 `_naturalize_triple()`（`services/svo_service.py:1740`）的LLM輸出問題，還是 `merge_triples_to_graph()`（同檔`1953`行起）對同一條邊並發寫入`citations_json`/`natural_text`造成的read-modify-write race（本報告§3 T1已經查證過`merge_triples_to_graph()`單次呼叫內部循序、無並發，風險在**跨呼叫**）。步驟：(1) 唯讀查詢報告65 §10列出的具體案例，核對`natural_text`內容對應`citations_json`裡的哪一筆citation；(2) 用查到的subject/verb/object/type直接重跑`_naturalize_triple()`3-5次記錄是否重現洩漏。**環境變數**比照報告62 §7（`WORKSPACE_DIR=D:/Users/666/Desktop/kg-runtime`、`NEO4J_URI=bolt://localhost:17990`、`NEO4J_PASSWORD=kg2_test_2026`、`OLLAMA_BASE_URL=http://127.0.0.1:11434`），**全程唯讀，不要對Neo4j做任何寫入**。完成後把結論寫清楚（是LLM/prompt問題、race問題、還是無法判定）並回報，**不要自己接著做T2/T3/T4**——我會看過T1結論後再決定後續指令，因為T2/T3的實際寫法（要不要新增核對函式、prompt怎麼改）取決於T1的判定。
