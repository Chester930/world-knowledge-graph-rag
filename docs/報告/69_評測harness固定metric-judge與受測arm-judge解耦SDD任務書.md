# 69 評測harness固定metric-judge與受測arm-judge解耦SDD任務書（交付Codex）

**建立日期**：2026-09-22
**文件性質**：任務書，交付 Codex 執行，完成後由 Claude Code 複驗。
**觸發脈絡**：用報告68的`--embedding-cache`重跑獨立judge pilot（7題，共用judge vs獨立judge qwen3.5:4b），確認embedding快取本身有效（兩次跑的檢索分數逐位元相同），但**7題中有4題（`57-CANARY5`／`57-AGGR7`／`57-AGGR8`／`57-AGGR19`）的Stage 1 Context Recall仍隨受測judge換人而變動**。查明根因：`services/semantic_span_matcher.py::match_spans_with_fallback()`在逐字比對失敗時會呼叫`judge_llm_provider`做語意蘊含核對，而`scripts/eval/run_rq1_comparison.py`目前對Stage 1（檢索）、Stage 2（context組裝）、Stage 3（AtomicScorer）、Stage 4（`build_full_lineage_async`）**全部共用同一個、隨受測arm變動的`judge_counting`實例**。文獻查證（`docs/參考文獻/39_LLM評判者一致性與固定化評測量尺/README.md`）確認這更準確的定性是**評判者間信度（inter-rater reliability）問題**而非self-preference bias，且Zheng et al. 2023（arXiv:2306.05685，LLM-as-Judge奠基文獻）自己的方法論就是「用同一顆固定外部judge評分所有受測模型」——本任務書據此設計修法。

---

## 0. 一頁摘要

**目標**：讓評測harness（`scripts/eval/run_rq1_comparison.py`／`scripts/eval/frozen_baseline_stage.py`）能把「**受測arm自己的judge**」（只影響`chat()`內部/生成路徑的重生成決策，這是真正想測的東西）與「**評分工具的judge**」（Stage 1/2/3/4量測分數用，理應跨所有arm固定一致）分開，避免「換了受測judge」同時污染了「量出來的分數本身怎麼算」。

**範圍**：**只動評測harness層與`core/providers/factory.py`新增一個eval-only的建構函式，完全不動`routers/agent.py`／`services/`下任何production程式碼**。production `chat()`的judge解析邏輯（`get_judge_llm_provider()`／`settings.judge_llm_provider`）維持完全不變。

**預設行為**：不傳新的`--metric-judge-provider`/`--metric-judge-model`時，**完全零行為變化**——所有Stage 1-4沿用現況的`judge_counting or counting`，跟這次任務書執行前逐字相同。

---

## 1. 現況（已查證，供直接引用）

1. `scripts/eval/run_rq1_comparison.py::_run_single_query()`（第218-389行）有5處把`judge_counting or counting`當作`judge_llm_provider`傳入：
   - 第264行：`agent._generate_from_context_lines(...)`——**僅B0/B1 baseline arm**用，直接影響生成路徑的重生成決策，是**受測arm本身的行為**。
   - 第315行：`tracker.record_retrieval_async(...)`——Stage 1檢索血統，內部呼叫`match_spans_with_fallback()`做語意fallback核對，**是量測工具**。
   - 第323行：`tracker.record_context_assembly_async(...)`——Stage 2 context組裝血統，同樣呼叫語意fallback，**是量測工具**。
   - 第361行：`AtomicScorer.evaluate_async(...)`——Stage 3原子事實評分，核心評分函式，**是量測工具**。
   - 第374行：`tracker.build_full_lineage_async(...)`——Stage 4彙總血統，**是量測工具**。
   - F/G/K/K-2b arm（本專案目前所有實驗都用的`K` arm屬此類）透過`_drain_chat(_build_kg_chat_request(...))`呼叫production `chat()`，`chat()`內部自己的judge由`settings.judge_llm_provider`/`JUDGE_LLM_MODEL`環境變數決定，**不經過**第264行這條路徑——這條路徑只有B0/B1 arm會用到。
2. `judge_counting`／`counting`在`_run_harness()`（第646-739行）建立：第656-657行`generator = get_llm_provider()`／`judge = get_judge_llm_provider(generator)`，第690-691行包成`_CountingLLM`。`get_judge_llm_provider()`（`core/providers/factory.py:117-125`）讀全域`_judge_llm`，由`init_providers()`依`settings.judge_llm_provider`/`settings.judge_llm_model`（即環境變數`JUDGE_LLM_PROVIDER`/`JUDGE_LLM_MODEL`）建立——**這正是這次pilot之所以能透過環境變數換judge、同時污染Stage 1-4量測的原因**。
3. `core/providers/factory.py::_make_llm_provider(provider_name, model_override=None)`（第14-57行）已存在，依明確傳入的`provider_name`/`model_override`建構provider，**不讀`settings.judge_llm_provider`/`settings.judge_llm_model`**（只讀該provider自己的api_key/base_url欄位），適合直接拿來建一個**不受`JUDGE_LLM_PROVIDER`環境變數影響**的固定metric-judge。目前是模組私有函式（前綴`_`），沒有對外的public包裝。
4. `frozen_baseline_stage.py::build_run_command()`（第77-95行）已依報告68的先例，佈線過一次選填透傳（`--embedding-cache`），本任務書比照同一模式新增`--metric-judge-provider`/`--metric-judge-model`透傳。
5. **不影響凍結基準的重要澄清**：報告57 §4.20的凍結基準評測（42題）在單次harness呼叫內只用**一個固定**judge設定跑完所有arm（M1-M4/K等retrieval策略），**不會**在同一次跑裡換judge——這次發現的confound只在像本次「明確設計成跨run換judge的pilot」才會暴露，**不影響已完成的凍結基準結果**，不需要回頭檢討報告57的數字。

---

## 2. 設計

### 2.1 `core/providers/factory.py`新增eval-only建構函式

```python
def make_llm_provider_for_eval(provider_name: str, model_override: str | None = None) -> LLMProvider:
    """僅供離線評測harness使用：建立一個獨立於全域 _llm/_judge_llm 單例、且不受
    settings.judge_llm_provider/JUDGE_LLM_MODEL 環境變數影響的 LLM provider 實例，
    供 harness 的固定 metric-judge 使用（Stage 1-4 語意核對/評分工具，理應跨所有
    受測arm/pilot一致，不應隨 JUDGE_LLM_PROVIDER 這類環境變數變動）。不需要先呼叫
    init_providers()——本函式只依傳入參數建構，不讀取/寫入任何全域單例。
    """
    return _make_llm_provider(provider_name, model_override)
```

放在`override_embedding_provider_for_eval()`附近，docstring風格比照它（明確標示eval-only）。

### 2.2 harness CLI新增選填參數

`run_rq1_comparison.py::build_arg_parser()`新增（緊接`--embedding-cache`之後）：

```python
parser.add_argument(
    "--metric-judge-provider", default=None,
    help="選填：固定評分工具judge的provider（例如ollama），獨立於受測arm自己的"
         "JUDGE_LLM_PROVIDER，用於Stage1-4語意核對/評分；不傳則沿用現況（Stage1-4"
         "跟受測arm共用同一顆judge，行為零變化）。",
)
parser.add_argument(
    "--metric-judge-model", default=None,
    help="選填：搭配--metric-judge-provider使用，指定metric-judge的model；"
         "不傳則用該provider在settings的預設model欄位。",
)
```

`frozen_baseline_stage.py`的`build_run_command()`／`run`子命令新增對應透傳（同樣預設不傳）。

### 2.3 `_run_harness()`／`_run_single_query()`接線

`_run_harness()`（第646行起）在建立`judge_counter`之後，新增：

```python
metric_judge_provider_name = getattr(args, "metric_judge_provider", None)
metric_counter = None
if metric_judge_provider_name:
    metric_judge = make_llm_provider_for_eval(
        metric_judge_provider_name, getattr(args, "metric_judge_model", None)
    )
    metric_counter = _CountingLLM(metric_judge)
```

`_run_single_query()`簽名新增`metric_counter: _CountingLLM | None = None`參數（`_run_harness()`呼叫時一併傳入），函式開頭比照現有`judge_counting`的reset邏輯補上`metric_counter`的reset。

**只改Stage 1-4這4處**（第315/323/361/374行），把`judge_llm_provider=judge_counting or counting`改成`judge_llm_provider=metric_counter or judge_counting or counting`：
- 第315行 `record_retrieval_async`
- 第323行 `record_context_assembly_async`
- 第361行 `AtomicScorer.evaluate_async`
- 第374行 `build_full_lineage_async`

**第264行（B0/B1 arm的`agent._generate_from_context_lines`）明確不改**，維持`judge_llm_provider=judge_counting or counting`——這是受測arm自己的生成路徑行為，不是量測工具，不應該被metric_counter覆蓋。

### 2.4 manifest記錄

`manifest`字典（`_run_harness()`後段組裝處）新增：
```python
"metric_judge_provider": metric_judge_provider_name,
"metric_judge_model": getattr(args, "metric_judge_model", None) if metric_judge_provider_name else None,
```
不傳新旗標時兩個欄位皆為`None`，跟其他既有欄位（`judge_provider`等）風格一致，方便事後稽核這次跑有沒有用固定metric-judge。

---

## 3. 任務清單

### T1（S）：`core/providers/factory.py`新增`make_llm_provider_for_eval()`＋單元測試

- 依§2.1實作。測試涵蓋：不需要先呼叫`init_providers()`（跟`override_embedding_provider_for_eval()`的行為明確不同，測試要能區分這點）；不同`provider_name`/`model_override`組合建出不同instance；回傳的instance不是全域`_llm`/`_judge_llm`（呼叫後這兩個全域單例不受影響）；不支援的`provider_name`拋`ValueError`（跟既有`_make_llm_provider`行為一致）。

### T2（S）：harness CLI＋`_run_harness()`接線＋manifest欄位＋單元測試

- 依§2.2/§2.3/§2.4實作`run_rq1_comparison.py`部分。測試涵蓋：不傳新旗標時`metric_counter`為`None`、manifest兩個新欄位皆為`None`；傳了`--metric-judge-provider`後`metric_counter`確實被建立且是獨立instance（不是`judge_counter`本身）。

### T3（S）：`_run_single_query()`四處call site改動＋回歸測試

- 依§2.3把第315/323/361/374行改成`metric_counter or judge_counting or counting`，第264行明確不動。測試涵蓋：用一個假的`_CountingLLM`分別當`counting`/`judge_counting`/`metric_counter`，斷言Stage1-4的`judge_llm_provider`實際收到的是`metric_counter`（當有傳入時）；B0/B1 arm路徑（第264行）斷言收到的仍是`judge_counting or counting`、不受`metric_counter`影響；不傳`metric_counter`（`None`）時四處都退回`judge_counting or counting`，跟修改前逐字相同（golden-test精神）。

### T4（S）：`frozen_baseline_stage.py`透傳＋回歸測試

- 依§2.2新增`--metric-judge-provider`/`--metric-judge-model`透傳到`build_run_command()`。測試涵蓋：不傳時`cmd`跟現況逐字相同；傳了會出現在組出的command list裡。

### T5（S，驗證用，不要自動執行大規模實驗）：重跑一次獨立judge pilot驗證confound是否解決

用今天已有的7題（`.claude/tmp/report65_targeted_karm_20260922/questions.json`）與同一份embedding快取（`.claude/tmp/report68_embedding_cache_20260922/embedding_cache.json`），這次額外固定`--metric-judge-provider ollama --metric-judge-model qwen2.5:7b`（跟共用judge臂的judge一致，方便跟`.claude/tmp/report68_embedding_cache_20260922/run1_cached/records.json`直接比對），跑一次獨立judge臂（`JUDGE_LLM_PROVIDER=ollama JUDGE_LLM_MODEL=qwen3.5:4b`，`--allow-shared-judge`，`--out .claude/tmp/report69_metric_judge_fixed_20260922/run_independent_judge_fixed_metric`）。**關鍵驗收**：這次7題的Stage 1 Context Recall應該要跟`run1_cached`**完全一致**（因為metric-judge固定了，不再隨受測judge變動）——如果還是不一致，代表修法沒有真正解決confound，要回報而不是隱瞞。**不要覆寫先前的資料夾**，輸出到新路徑。**跑之前務必確認沒有其他Claude session在用同一組Neo4j/Ollama**（可用ListAgents/SendMessage協調），唯讀不寫KG。

---

## 4. 明確不做的事

- **不修改`routers/agent.py::chat()`或任何production程式碼**——production的judge解析邏輯（`get_judge_llm_provider()`／`settings.judge_llm_provider`）完全不變。
- **不改第264行（B0/B1 arm）的judge來源**——那是受測arm自己的行為，不是量測工具，不應該被metric_counter覆蓋。
- **不強制Stage 3/4一定要用metric-judge**——`--metric-judge-provider`維持選填，不傳時現況（含已完成的報告57凍結基準）完全不受影響。
- **不需要回頭重跑或修正報告57的凍結基準**——那次評測沒有跨judge比較，不受這個confound影響。
- **不自動對KG做任何寫入**，T5只唯讀查詢。
- **不需要修改AtomicScorer或semantic_span_matcher.py本身的邏輯**——這兩個檔案的行為完全不變，只是harness層決定要傳哪個judge instance進去。

---

## 5. 驗收標準

1. `python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py` 全綠，新增測試反映T1-T4實際新增的邏輯。
2. `--metric-judge-provider`/`--metric-judge-model`不傳時，兩個harness腳本行為與目前逐字相同（golden-test精神，比照報告66/68的做法）。
3. T5的驗證結果（有固定metric-judge時，Stage 1 Context Recall在共用judge臂與獨立judge臂之間是否真的完全一致）附在commit message或本報告新增小節，**無論結果是否如預期都要如實回報**。
4. 不需要對KG做任何寫入；commit前不需要額外詢問，但完成後不要自動接著做T5以外的任何延伸實驗（例如不要自動重跑凍結基準、不要自動擴大題庫）。

---

## 6. 給 Codex 的指令（可直接貼上）

> 請執行 `docs/報告/69_評測harness固定metric-judge與受測arm-judge解耦SDD任務書.md` 的 T1-T5。背景：報告68的embedding快取確認有效（檢索分數逐位元決定性），但重跑獨立judge pilot後發現7題中4題的Stage 1 Context Recall仍隨受測judge換人而變，查明根因是harness對Stage1(`record_retrieval_async`)/Stage2(`record_context_assembly_async`)/Stage3(`AtomicScorer.evaluate_async`)/Stage4(`build_full_lineage_async`)全部共用同一個隨受測arm變動的judge，而這4個都是「量測工具」不是「受測行為」。**範圍限定**：只動`core/providers/factory.py`（新增明確標示eval-only的`make_llm_provider_for_eval()`，直接複用已存在的`_make_llm_provider()`）與`scripts/eval/`下的檔案（`run_rq1_comparison.py`新增`--metric-judge-provider`/`--metric-judge-model`選填參數並接線到第315/323/361/374行這4處，**第264行B0/B1 arm的judge來源明確不要動**；`frozen_baseline_stage.py`比照報告68的`--embedding-cache`先例新增透傳），**完全不要修改`routers/agent.py`或任何production程式碼**。預設（不傳新旗標）必須是零行為變化。T1-T4依報告§3實作＋單元測試；T5用`.claude/tmp/report65_targeted_karm_20260922/questions.json`跟`.claude/tmp/report68_embedding_cache_20260922/embedding_cache.json`（沿用既有快取），固定`--metric-judge-provider ollama --metric-judge-model qwen2.5:7b`，跑一次`JUDGE_LLM_PROVIDER=ollama JUDGE_LLM_MODEL=qwen3.5:4b --allow-shared-judge`的獨立judge臂，輸出到新路徑`.claude/tmp/report69_metric_judge_fixed_20260922/run_independent_judge_fixed_metric`（不要覆寫`report68_embedding_cache_20260922`或`report65_targeted_karm_20260922`下的既有資料夾），跟`.claude/tmp/report68_embedding_cache_20260922/run1_cached/records.json`比對7題的Stage 1 Context Recall是否**完全一致**，如實回報結果（不管是否如預期）。跑T5前請先用ListAgents/SendMessage確認沒有其他Claude session在用同一組Neo4j/Ollama，全程唯讀不寫KG。完成後跑`python -m pytest tests -q -p no:cacheprovider --ignore=tests/core/test_embedding_migration.py`確認全綠並回報結果；commit前不需要額外詢問，但**不要**對KG執行任何寫入，也不要自動接著做T5以外的延伸實驗（例如不要自動重跑凍結基準或擴大題庫）。
