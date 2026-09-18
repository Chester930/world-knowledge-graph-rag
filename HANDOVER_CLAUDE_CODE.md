# Claude Code 接手導引（Quick Handover Guide）

> **目前進度請先讀**：[跨 Agent 接續進度 HANDOVER.md](HANDOVER.md)。本檔案記錄較早的 Claude Code 交接狀態；若狀態或建議與 HANDOVER.md 不同，以 HANDOVER.md 及最新報告為準。

詳細交接任務書請參閱：[`docs/報告/47_Claude_Code交接任務書.md`](docs/報告/47_Claude_Code交接任務書.md)

> ⚠️ **編號訂正（2026-09-14，入庫時補記，審查已完成）**：本文件與其引用的交接任務書原編號 46，建立時只存在主要 checkout 目錄、從未 `git commit`，因與已入庫報告衝突改編號 47；引用之「43_黃金版Benchmark」同步訂正為「44」。**「66/66 測試通過」已核實屬實**（實際重跑確認，過程中另修復 1 個真迴歸，全套 897 passed）；審查同時發現 3 個需留意的問題（`cost_analyzer` 估計值誤標實測、`query_classifier` 對題庫過擬合、題庫重複 id 已修復）與 1 個未完成項（`run_rq1_comparison.py` 的 `main()` 尚未串接實際跑測邏輯）——完整清單見 `docs/報告/47_Claude_Code交接任務書.md` 文首訂正。

文件閱讀順序與角色：

1. 本文件：一頁式入口、目前狀態與快速限制。
2. `docs/報告/47_Claude_Code交接任務書.md`：Claude Code 的工程任務與執行順序。
3. `docs/報告/44_黃金版Benchmark與評測修正任務書.md`：Gold、Benchmark、評分規則與驗收標準。

---

## 快速摘要

### 1. 三大架構鐵律
- **Zero Code-Gen 哲學**：核心 Python 代碼完全通用固化，絕不因新增領域/KG 自動生成 Python 程式碼；所有特異性由宣告式 Pydantic 參數檔（`DomainPack`, `ChunkingConfig` 等 JSON/YAML）驅動。
- **因果血統不變式**：嚴格隔離建圖、檢索、生成三階段成本；切塊注入主旨時，`source_sentence_start/end` 原始實體行號絕不偏移。
- **確定性接地守衛**：法律時效起算點、法條條號跨文覆核、查表缺口由規則守衛強制把關，防止同質弱 LLM 平滑化（「當月一日」變「當日」）。

### 2. 當前測試狀態（聲稱 66/66 PASSED，⚠️ 尚待審查驗證）
```bash
pytest tests/core/test_kg_config.py tests/services/test_svo_chunking.py tests/services/test_lineage_tracker.py tests/services/test_evaluation_metrics.py tests/services/test_deterministic_guards.py tests/services/test_adaptive_behavior_tree.py
```

以上結果代表 SDD 階段一至五的核心模組與單元測試已完成；**不代表階段五的主旨錨定已經接入實際抽取管線**。實際抽取管線接線仍是下一步任務 B。

目前 `data/eval/test_cases.json` 共 34 題，其中僅 10 題標記為 `verification_status=verified`（包含 2 題 Canary），另有 24 題 `unverified`。未完成真值核驗前，不得將全部 34 題納入正式評測。

### 3. 下一步三大任務
1. **任務 A**：先完成評測題目 eligibility filter，再執行端到端評測實驗 Harness（`python scripts/eval/run_rq1_comparison.py`），進行 M1~M4 評分。
2. **任務 B**：將 `ChunkingConfig` 主旨錨定接上實際抽取管線（`services/svo_preprocessing_service.py::prepare_svo_ready_chunks()`、`services/svo_service.py::trigger_extraction()`；`services/extraction_worker.py` 負責消費已產生的 SVO index）。
3. **任務 C**：將任務 A 實驗數據填補至論文第五章，完成消融分析。

執行分流：

- **Track A**：凍結目前 KG 與程式版本，先取得現況端到端評測基準。
- **Track B**：接入主旨錨定並重新建圖；完成後必須建立新的 KG／manifest，不能覆寫 Track A 基準。
- 任務 C 只能使用已凍結版本、已記錄 manifest 的結果。
