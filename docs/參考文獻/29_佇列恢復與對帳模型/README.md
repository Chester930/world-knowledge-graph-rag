對應 `../../論文/03_系統設計與方法論.md` § 3.1.2「抽取任務佇列與斷點續傳」的 `RESTART`／`TRUST`／`SCAN`／`REBUILD` 分支。與第二章文獻探討無直接對應——3.1 屬 🔧 工程借鏡型機制、不對應任何 RQ；§ 3.1.2 的 traceability 註記已明言「SQLite queue and recovery state machine are this project's own engineering design; no external queue project is claimed as a direct implementation source」。本資料夾**不推翻該聲明**：這裡的文獻只佐證「重啟後的恢復模型」是業界成文模式（level-triggered reconciliation），不宣稱佇列實作本身抄自任何專案。

2026-09-10 新增：Pass 2 逐層審視 L3（§ 3.1.2）時，發現 `services/task_queue_service.py::ensure_ready()` 的「索引可信」分支只做 `reset_stuck_processing()`，等同**信任每個 `trigger_extraction()` 事件都成功寫進 `task_queue.db`**——若行程死在 `CHUNKREADY` 完成、`enqueue()` 之前，乾淨重啟後這份文件不會被任何機制撿回（`rebuild_from_records()` 的 per-doc 對帳只在「索引不可信」才跑）。修正方向（G1）：讓「可信」分支也對每份 `_record.json`（真實狀態來源）做一次輕量對帳，補上缺漏的 pending 登記。此即把 edge-triggered 的恢復改為 level-triggered。本篇文獻是該模式的權威來源。

## 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `burns-et-al-2016-borg-omega-kubernetes.pdf` | Burns, Grant, Oppenheimer, Brewer & Wilkes (2016), *Borg, Omega, and Kubernetes: Lessons learned from three container-management systems over a decade* | 🟢 **ACM Queue 14(1)**, Jan–Feb 2016（本 PDF 版本）；同文亦刊於 🟢 **Communications of the ACM 59(5)**, May 2016；DOI: 10.1145/2898442.2898444；dblp `journals/cacm/BurnsGOBW16` |

## 產業慣例查證（無 PDF，直接查證官方文件，記錄於此供追溯）

| 專案 | 查證結果 | 來源 |
|---|---|---|
| **Kubernetes**（`kube-controller-manager` 及各內建 controller） | 內建 controller（ReplicaSet、Deployment、Job 等）皆為 reconciliation loop：每次觸發（事件、resync、重啟）都重新讀取 API server 上的 desired spec 與叢集 observed state，計算差異並收斂——不依賴「觸發它的事件內容」。這正是本專案 `rebuild_from_records()` 已採用、G1 要推廣到「可信」分支的模式。 | Kubernetes 官方文件「Controllers」概念頁；`kubernetes/kubernetes` 原始碼 |
| **`sigs.k8s.io/controller-runtime` / kubebuilder** | 官方 controller 開發框架，明文規範「`Reconcile()` 必須 **level-triggered 且 idempotent**——從當前世界狀態推導 desired state，不從觸發事件推導」，並將此列為 controller 正確性的第一原則。 | The Kubebuilder Book「What is a Controller」；`kubernetes-sigs/controller-runtime` 文件 |

## 各文獻在本節設計討論中的角色

- **Burns et al. (2016)**：本節唯一、也是足夠的錨點。原文第 13/24 頁（acmqueue Jan–Feb 2016, p.83）明確描述本專案 `RESTART` 恢復所依據的模式：

  > "The idea of a **reconciliation controller loop** is shared throughout Borg, Omega, and Kubernetes to improve the resiliency of a system: it compares a **desired state** … against the **observed state** …, and takes actions to converge the observed and desired states. **Because all action is based on observation rather than a state diagram, reconciliation loops are robust to failures and perturbations: when a controller fails or restarts it simply picks up where it left off.**"

  對應到本專案：`_record.json`（含 `extraction_status`／`completed_chunk_indices`／`svo_index.json`）是 desired／observed state 的來源，`task_queue.db` 是收斂目標的衍生索引。重啟時**重新讀記錄檔推導佇列該有的狀態**，而非信任「每個 `trigger_extraction` 事件都成功登記過」（後者是 state-diagram／edge-triggered 思維，正是原文說會 brittle 的那種）。

  ⚠️ **適配度誠實標註**：(1) 原文談的是分散式叢集控制器（多副本、API server 為中央 desired-state store），本專案是單機、單一背景 asyncio Worker、記錄檔散落於各 KG 資料夾——規模與拓撲差很多，只借「恢復模型」這一層概念，不借其分散式一致性機制；(2) 本專案的 `rebuild_from_records()` **早已是** reconciliation 模式，G1 不是引入新機制，而是修正「這個模式只在 index 損毀時才跑、正常重啟時被 edge-triggered 的 `reset_stuck_processing` 取代」這個不一致；(3) § 3.1.2 既有聲明「佇列實作為本專案自行設計」仍然成立——本篇只佐證恢復模型，不是佇列的實作來源。
