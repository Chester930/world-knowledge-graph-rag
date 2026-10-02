# 報告241：P3 拋棄式 Neo4j 驗證 Fact 層狀態設計風險執行紀錄

> 日期：2026-10-02
> 
> 性質：報告240 的 Codex 執行紀錄。這是合成資料上的五個風險點驗證，不是整個關係狀態機落地的驗證；規劃對話（Claude）將另行獨立驗證，本報告不以本身執行結果宣稱「已驗證」。

## 1. 執行邊界與 T0

依使用者在任務書中的三項明確確認，使用一次性的 `kg2-throwaway-neo4j`，映像為 `neo4j:5.26-enterprise`，埠為 `27474:7474`／`27687:7687`，記憶體上限 `3g`，沒有 volume、bind mount、host network、privileged 或 restart。未執行 `docker pull`，未對 `kg2-neo4j` 執行 `exec`／`logs`／完整 inspect，也未讀取專案 `.env`。

新增驗證腳本 `scripts/analysis/disposable_fact_state_validation.py`，其連線閘門只允許 `localhost`／`127.0.0.1:27687` 與合成 `kg_id`；會拒絕受保護 KG 的 `kg_id`、受保護埠與含 `kg2-neo4j` 的 URI。臨時密碼由記憶體內 `secrets` 產生，只以子程序環境傳給 `docker run` 與驅動，沒有寫入輸出 JSON、報告或命令列參數。

T0 純函式／閘門測試：**9 passed**。production 檔案（`services/`、`routers/`、`core/`）零修改；新腳本沒有把關係狀態接進現有執行路徑。

開始與結束僅以允許的 `docker inspect --format '{{.State.Status}}|{{.State.StartedAt}}' kg2-neo4j` 取得：

| 欄位 | 開始 | 結束 |
|---|---|---|
| State.Status | `running` | `running` |
| State.StartedAt | `2026-10-01T12:36:49.303373783Z` | `2026-10-01T12:36:49.303373783Z` |

## 2. T1 五情境

輸出原始 JSON：[`disposable_fact_state_validation_20261002.json`](../../data/analysis/disposable_fact_state_validation_20261002.json)。所有資料均為腳本建立的虛構 Fact；向量為 8 維決定性向量。

| 情境 | 現行行為 | 腳本內提案行為 | 是否符合 233／234 推論 |
|---|---|---|---|
| C1 去重風險 | `vector_search_facts(top_k=1)` 留下向量分數 `1.0` 的 `c1-old`（`已被取代`）；新版分數 `0.99736214` | 先過濾可檢索狀態，再去重，留下 `c1-new`（`有效`） | 是 |
| C2 撤銷 | `revoke_chunk_facts` 前有 1 個 Fact，後為 0；`facts_deleted=1`、`edges_deleted=1` | 同一概念在腳本內追加 `撤銷` 事件，保留 Fact，設 `已駁回`；可檢索數為 0 | 是 |
| C3 BFS 只看邊 | `bfs_query` 仍回傳 1 條 `RELATED_TO` 邊；耗時約 `0.334259 s` | Fact 狀態聚合後 1 個 Fact、可檢索 0；加入 1,000 筆合成 Fact 後總數 1,001、可檢索 0，聚合查詢約 `0.167762 s` | 是 |
| C4 缺席狀態 | 同鍵中現行去重留下更近的 `c4-superseded`（分數 `1.0`） | 以 `IS NULL OR IN [候選,有效,爭議]` 先過濾後，缺席狀態 `c4-missing`（分數 `0.99016762`）仍留下 | 是 |
| C5 事件／快取漂移 | 追加後快取為 `有效`；2 個事件重播為 `有效`，`replay_ok=true` | 手動把快取改為 `已駁回`，稽核比對偵測漂移 | 是 |

五項 `matches_inference` 均為 `true`。C1、C4 直接呈現報告234 §4 所說的「狀態過濾必須先於 `(subject, relation, object)` 去重」；C2 呈現現行實體刪除與不可變事件提案的差異；C3 呈現 BFS 不讀 Fact 狀態；C5 呈現事件重播與快取稽核的可行性。

## 3. T2 收尾與誠實揭露

臨時容器收尾紀錄：`docker stop` exit code **0**、`docker rm` exit code **0**；拆除前名稱為 `kg2-throwaway-neo4j`，拆除後 `docker ps -a --filter name=^/kg2-throwaway-neo4j$` 無輸出。輸出 JSON 的 `temp_absent_after=true`、`kg4_unchanged=true`。

合成圖只有 `RELATED_TO`；production `bfs_query` 的關係型別清單還包含未在合成圖建立的其他型別，因此 Neo4j 發出「relationship type does not exist」通知，但 `RELATED_TO` 仍正常回傳 1 筆。這是小型合成環境的可預期通知，不是資料或 production 的修改；另有既有 `requests` 依賴版本警告。兩者均已記錄於輸出 JSON 的 `environment_observations`。

限制如下：

- 合成資料不代表真實資料分布，只有單一小型圖；約 1,000 筆查詢數字只供量級參考。
- 沒有驗證 W1／W4／W5 寫入端、抽取端、真實 KG 的檢索品質、回答品質或完整遷移／回填。
- 沒有對 KG#4 寫入任何欄位，也沒有把 `relation_lifecycle` 接進現有 production 路徑。
- 實驗環境是任務指定的 Neo4j 5.26 Enterprise 臨時容器；不能外推到其他 Neo4j 版本或部署設定。

待使用者裁示（本報告只列，不代決）：

1. 是否採用 Fact 狀態欄位與事件清單，以及正式欄位／事件 schema。
2. 關係邊在多個 Fact 狀態下的聚合規則與空 Fact 行為。
3. 舊 Fact 缺席狀態的遷移／回填策略，以及預設可檢索狀態集合。
4. 撤銷流程是否由實體刪除改為追加事件並保留 Fact。
5. 狀態過濾、去重、索引與現有檢索／BFS 的接線時機與範圍。

