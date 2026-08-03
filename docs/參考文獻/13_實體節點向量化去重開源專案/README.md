對應 `../../論文/03_系統設計與方法論.md` § 3.1.4「實體對齊/去重」（`DEDUP4`／`resolve_entity_name()`）——目前該機制對 `Entity` 節點沒有持久化 embedding，每次比對都即時呼叫 `embedding_provider.encode()`，跟 `Chunk.embedding`／`RELATED_TO.verb_embedding`／設計中的 `Fact.fact_embedding` 的既有慣例不一致。本資料夾收錄「Entity 節點該不該存 `name_embedding` ＋建向量索引」這個設計選項的候選文獻與開源專案。

> **狀態：✅ 2026-08-03 已實作**（`name_embedding` 屬性＋fallback 漸進部署，`services/svo_service.py`，測試見 `tests/services/test_svo_service.py`）；**🟡 向量索引 KNN 查詢與批次回填函式刻意排除於本次範圍，留待後續**。完整設計定案內容見 `03_系統設計與方法論.md` § 3.1.4 `DEDUP4` 段落新增的「Entity 節點向量化效能改造」註記。本資料夾內容仍為初次查證層級（`gh api` 驗證 star 數、下載可公開取得的全文 PDF，**尚未逐字精讀全文**）——機制本身已定案並實作不代表文獻已達精讀標準，兩者是獨立的判準，比照 `12_三元組事實層級向量化與檢索/` 從「初次查證」到「全文精讀」的兩階段模式，本資料夾文獻查證仍處於第一階段，若後續要提升信任分級需另外補齊全文精讀。

## 查證背景（2026-08-03）

使用者盤點 `resolve_entity_name()` 現況後，確認 Entity 節點去重是全系統中唯一沒有把 embedding 持久化＋建向量索引的環節。先由 fork agent 廣泛蒐集「圖譜向量化」四個子主題（節點去重索引化、型別語意比對、傳統 KGE、社群層級向量化）的候選文獻與專案，使用者接著指定「只看 1000★ 以上的開源專案，並找出其背後的技術文獻」，本次針對篩選後的三個專案（Splink、neo4j-labs/llm-graph-builder、Zingg）逐一深入查證。

## 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `enamorado-fifield-imai-2019-fastlink.pdf` | Enamorado, Fifield & Imai (2019), *Using a Probabilistic Model to Assist Merging of Large-Scale Administrative Records*，**American Political Science Review** 113(2), 353-371 | [開放取用全文](https://imai.fas.harvard.edu/research/files/linkage.pdf)（作者自存版） |
| `linacre-et-al-2022-splink.pdf` | Linacre, Lindsay, Manassis, Slade, Hepworth, Kennedy & Bond (2022), *Splink: Free software for probabilistic record linkage at scale*，**International Journal of Population Data Science** 7(3) | DOI: [10.23889/ijpds.v7i3.1794](https://doi.org/10.23889/ijpds.v7i3.1794)（開放取用期刊） |

## 三個 1000★+ 開源專案的技術文獻查證結果

### 1. `neo4j-labs/llm-graph-builder`（4,979★，✅ `gh api` 已查證，活躍：最後 push 2026-08-01）

Neo4j 官方（Neo4j Labs）用 LLM 從非結構化資料建圖的參考實作，**在本論文 `02_文獻探討.md` § 2.4.2 已被引用過一次**（作為 WhyHow.ai 熱度對照的業界規模基準，約 4,955★），本次是首次針對其「節點向量化＋去重」機制深入查證。

**① 實體節點向量化（`backend/src/post_processing.py`）**：`__Entity__` label 統一存 `embedding` 屬性，`CREATE VECTOR INDEX entity_vector ... FOR (n:__Entity__) on (n.embedding)`——與本專案討論中的 `Entity.name_embedding` + 向量索引設計同構。embedding 內容是 `e.id + " " + coalesce(e.description, "")`（**名稱＋描述合併**，非本專案現行單純 `name`）。**時機是批次回填**：`create_entity_embedding()` 掃描 `e.embedding IS NULL` 的節點，1000 筆一批計算——節點先正常建立、embedding 之後才補算，不是建立當下就算。

**② 去重比對邏輯**（`backend/src/graphDB_dataAccess.py::get_duplicate_nodes_list()`）：同時用三種訊號判斷是否重複——substring containment、`apoc.text.distance()`（編輯距離，門檻 3）、`vector.similarity.cosine(other.embedding, n.embedding) > 0.97`。偵測後由**使用者在前端 UI 手動觸發** `merge_duplicate_nodes()`，用 APOC 內建的 `apoc.refactor.mergeNodes()` 合併，不是抽取當下自動判定。

**背後技術文獻查證結果**：
- **社群偵測／摘要部分**：官方文件與多篇第三方文章（Neo4j 官方部落格、Medium）明確說明「基於 Microsoft 的 GraphRAG 論文」——即本論文已引用的 **Edge et al. (2024)**，社群偵測用 Leiden 演算法（`gds.leiden.write`，程式碼內未附論文引用，Leiden 演算法本身的原始文獻為 Traag, Waltman & van Eck (2019)，本論文目前未引用，若後續要精確溯源可補查）。
- **實體向量化＋去重部分**：**查無對應學術文獻**——原始碼與官方文件皆未引用任何論文，屬於他們自己的工程設計（「編輯距離＋cosine 門檻」組合式判斷，跟本專案 DEDUP4「編輯距離→cosine≥0.88」設計精神一致，但雙方都查無同一篇上游文獻依據，屬於各自獨立收斂到相似工程解法）。

### 2. `moj-analytical-services/splink`（2,310★，✅ `gh api` 已查證，活躍：最後 push 2026-07-31）

英國司法部（UK Ministry of Justice）開發的生產級機率式紀錄比對系統，**已在本論文 `docs/參考文獻/03_資訊抽取與本體設計/README.md` 被引用**（作為 `BACKFILL` LLM 確認關卡設計的補充佐證），本次針對其「背後技術文獻」深入查證，找到兩層文獻依據：

**① 方法論源頭——fastLink（R 套件）**：Splink 官方文件（[Fellegi-Sunter 理論頁](https://moj-analytical-services.github.io/splink/topic_guides/theory/fellegi_sunter.html)）明確引用 **Enamorado, Fifield & Imai (2019)**《Using a Probabilistic Model to Assist Merging of Large-Scale Administrative Records》，*American Political Science Review* 113(2)——這篇是 R 套件 `fastLink` 背後的正式學術論文，用 EM 演算法求解 **Fellegi & Sunter (1969)** 模型（本論文已引用），Splink 官方文件明確聲明「採用的數學方法與 fastLink 非常相似」。這篇論文**可免費取得全文**（作者自存版，已下載），補上了本論文原本因 Fellegi & Sunter (1969) 付費牆而缺的「現代、免費、完整方法論細節」這一環。

**② Splink 本身的軟體論文**：**Linacre et al. (2022)**《Splink: Free software for probabilistic record linkage at scale》，*International Journal of Population Data Science* 7(3)，DOI: 10.23889/ijpds.v7i3.1794——開放取用期刊，已下載全文。這是 Splink 專案本身的正式軟體論文，描述其架構與 UK MoJ 的實際應用（Data First 計畫）。

**誠實限制**：Splink 官方文件中，embedding-based blocking（用向量相似度做候選生成）屬於**功能存在**，但本次查證**未找到專門描述這個功能的獨立學術文獻**——Splink 的核心理論文獻（fastLink／Fellegi-Sunter）談的是機率式比對模型本身，不是「embedding 存起來＋向量索引查詢」這個工程模式的直接依據；後者仍需依賴子主題 A 其他候選（如 Skoutas et al. 2023 VLDB 實驗分析）或前一輪找到的 `entity-embed`（161★，已停止維護，未達本次 1000★ 門檻）佐證。

### 3. `zinggAI/zingg`（1,233★，✅ `gh api` 已查證，活躍：最後 push 2026-07-28）

Spark-based 的 ML 實體解析／去重工具，用主動學習（active learning）從少量標註樣本（約 30-40 筆）訓練 pairwise classifier。

**⚠️ 誠實聲明：查無明確學術文獻依據**——查了官方文件首頁、`llms.txt` 索引、GitHub README，**皆未提及任何論文、arXiv 連結或具體演算法引用**。搜尋過程中找到一筆可能相關的美國專利（US 11,416,780，《Method and computer program product for training a pairwise classifier for use in entity resolution in large data sets》），但該專利 PDF 為純掃描影像檔，本次未能查證發明人／受讓人是否確實為 Zingg 團隊，**不列為可信引用來源**，僅記錄此線索供後續（若有需要）自行以 USPTO 官方檢索介面查證。

**結論**：Zingg 是本輪三個候選中唯一查無學術文獻依據的專案，若要引用，只能定位為「業界另一個獨立的生產級實作範例」（佐證「主動學習式實體解析」這個技術方向被廣泛採用），不能作為理論依據。

## 與子主題 A 前一輪候選的關係（去重複，見對話紀錄）

前一輪（未限定 1000★）還找到 `entity-embed`（161★，已停止維護）與 `qcri/DeepBlocker`（30★，已停止維護，⚠️付費論文無 arXiv 版）——本次因使用者要求聚焦 1000★+，兩者不重複收錄全文，僅在此記錄供追溯：`entity-embed` 的定位（PyTorch 函式庫，明確做「實體轉向量存起來＋ANN 索引取代線性掃描」）在機制上比本輪三個專案都更貼近本專案的具體技術問題，星數雖未達門檻，若使用者後續改變篩選標準，應優先重新納入考慮。

## 與本專案設計缺口的對應關係

三個 1000★+ 專案中，`neo4j-labs/llm-graph-builder` 是**機制上最直接對應**的——同一套資料庫技術（Neo4j）、`Entity.embedding` + 向量索引 + 編輯距離/cosine 組合去重，幾乎是本專案 DEDUP4 若要補上向量化的現成範例，且額外提供了「批次回填」與「embedding 內容應否含描述而非只有名稱」兩個本專案尚未考慮過的具體設計選項。`Splink` 提供的是**理論文獻鏈的延伸**（fastLink → Fellegi-Sunter，兩篇皆可免費全文精讀），補齊本論文原本因 1969 年論文付費牆而留下的查證缺口。`Zingg` 目前查無文獻依據，工程參考價值高於文獻價值。

## 尚未查證/待辦

- [ ] 三份文獻／專案原始碼皆僅初步瀏覽，未逐字精讀全文（含附錄），若後續決定採用 Entity 節點向量化設計，需要比照 `12_三元組事實層級向量化與檢索/` 的標準補齊全文精讀。
- [ ] `neo4j-labs/llm-graph-builder` 的 Leiden 社群偵測部分，原始文獻（Traag, Waltman & van Eck, 2019）本論文目前未引用，若本論文之後決定要更精確溯源社群偵測演算法本身（目前僅在 3.1 總覽標註「階層式 Leiden」，未附文獻），可視需要補查。
- [ ] Zingg 提及的美國專利（US 11,416,780）未查證是否確實屬於同一團隊，且專利本來就不符合本論文一貫的學術文獻標準，暫不列入正式引用候選。
- [ ] 子主題 A 前一輪的 `entity-embed`（161★）雖未達本輪 1000★ 門檻，其「向量化＋ANN 索引」機制描述比本輪三者都更貼近本專案問題本身，若使用者後續放寬星數門檻，應優先重新查證。
