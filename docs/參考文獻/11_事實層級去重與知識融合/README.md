對應 `../../論文/03_系統設計與方法論.md` § 3.1.4「事實層級去重」（`merge_triples_to_graph()` 的 MERGE 鍵設計：`(kg_id, subject, rel_type, object)`，來源改記錄在累積的 `citations_json`，`confidence` 屬性取所有引用中的最大值）。

## 查證背景（2026-07-26）

使用者於盤點 3.1.3 現況後追問：SVO 抽取整條管線中，除了型別（`SVO_REL_TYPES`／`ENTITY_TYPES`）已有文獻佐證外，其他部分是否也有查證。逐節盤點後發現**事實層級去重**這個設計——同一 `(subject, rel_type, object)` 若被多個不同 chunk／文件重複抽到，合併成單一邊、來源改累積記錄於 `citations_json`——是目前系統中**唯一完全沒有做過任何文獻/參考專案查證**的環節，連「查無文獻」的誠實聲明都尚未寫過。本資料夾收錄查證後找到的兩項功能性先例。

## 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `dong-et-al-2014-knowledge-vault.pdf` | Dong et al. (2014, Google), *Knowledge Vault: A Web-Scale Approach to Probabilistic Knowledge Fusion*, **KDD 2014**, pp. 601-610 | 開放取用：https://www.cs.ubc.ca/~murphyk/papers/kv-kdd14.pdf（Kevin Murphy 個人頁面，已逐字精讀全文） |
| （交叉引用，PDF 已存於 `../03_資訊抽取與本體設計/vrandecic-krotzsch-2014-wikidata.pdf`） | Vrandečić & Krötzsch (2014), *Wikidata: A Free Collaborative Knowledgebase*, **CACM** 57(10) | 已於 03 資料夾下載並精讀全文，本節重新引用其「Citation Needed」段落 |

## 兩項先例在本設計中的角色

### 1. Wikidata 的「一則陳述、多筆參考來源」結構（Citation Needed 機制）——佐證「資料結構」

Vrandečić & Krötzsch（2014）"Citation Needed" 一節明確指出：「In Wikidata, every such claim can include a list of references to sources that support the claim... a reference is simply a list of property-value pairs, leaving the details of reference modeling to the community.」官方統計數字佐證這是核心、大規模使用的機制，非邊緣功能：截至該文寫作時，**43,189,145 筆陳述（statements）中有 23,242,779 筆已附帶至少一筆參考來源**（約 54%）。這與本設計「一個事實三元組（單一 Neo4j 邊）可累積多筆 `citations_json` 條目」在**資料結構**層面幾乎直接對應——都是「單一陳述/邊 + 可變長度的來源清單」。

**誠實適配度**：Wikidata 的 reference 是**社群成員手動附加的支持性引用**（回答「這個陳述憑什麼可信」），而本設計的 `citations_json` 是**系統自動累積的抽取來源記錄**（回答「這個事實是從哪個 chunk／句子抽出來的」，服務可追溯性 AIS 指標）——兩者的**動機不同**（前者是知識論證、後者是抽取溯源），但**資料結構**（一則陳述對應可變長度來源清單）高度一致，可作為「此結構模式已在生產級系統證明可行」的獨立佐證。

### 2. Knowledge Vault 的多來源證據融合機制——佐證「問題成因與處理方向」

Dong et al.（2014）第 3.2 節「Fusing the extractors」與第 3.5 節「The beneficial effects of adding more evidence」直接處理與本設計**同一類問題**：同一個 `(subject, predicate, object)` 三元組可能被多個不同來源（web 文件）各自抽取出來，系統需要決定如何處理這種重複。具體機制：

- 特徵向量包含「這個三元組被幾個獨立來源抽到」（`sqrt(n)`，其中 n 是來源數）與「這些抽取的平均信心分數」兩項，餵給融合分類器計算最終信心分數（§3.2）。
- 圖 2／圖 3（§3.5）實證顯示：隨著抽到同一三元組的獨立來源數增加，該三元組為真的信心分數持續上升，佐證「多來源重複佐證應該提升、而非稀釋信心」這個方向。
- **關鍵的同源問題**：論文明確處理「同一網域內多篇頁面重複同一段內容」會虛灌證據數的問題，解法是**每個網域只計一次，而非每個 URL 各自計一次**（§3.5：「we only count each triple once per domain, as opposed to once per URL」），並在第 8 節「Dealing with correlated sources」承認這只是簡化解法，未來需要更完善的複製偵測機制。

這與本論文設計的問題結構**高度平行**：本論文的 MERGE 鍵重新設計，正是為了解決「同一事實若來自不同 chunk／句子，即使是完全不重疊的兩個 chunk 各自獨立提到同一事實，也會產生兩條邊」這個問題（見 3.1.4 節「事實層級去重」段落）——KV 的「同網域只計一次」與本論文的「同 kg_id 內 `(subject, rel_type, object)` 只保留一條邊」是同一類「避免重複來源虛灌證據/邊數」的問題，只是計數單位不同（網域 vs. 抽取三元組本身）。

**誠實適配度**：KV 解決的是**信心分數融合**（多筆來源 → 一個機率值，來源本身在融合後即被丟棄，不個別保留），而本設計解決的是**結構化來源保留**（多筆來源 → 累積成一份 `citations_json` 清單，逐筆保留，供人工回溯查看）——兩者要解決的下游需求不同（KV 要一個可信度分數；本論文要可追溯的引用清單），**具體機制不可直接套用**。此外，KV 的「信心隨獨立來源數增加而上升」與本論文現行設計「`confidence` 屬性取所有引用中的最大值」**方向不同**——本論文目前不會因為多筆引用而讓信心值上升，只是保留最高的單筆信心值；這是一個值得留意的設計差異，若未來要讓「多筆獨立來源佐證同一事實」也反映在信心分數上，KV 的「證據數量→信心融合」機制會是可參考的具體作法，但目前定案的「取最大值」設計並未採用這個方向。

## 尚未查證/待辦

- [ ] Knowledge Vault 論文引用的 [10]（Dong, Berti-Equille & Srivastava, 2009, VLDB, *Integrating conflicting data: the role of source dependence*）是其「更精細複製偵測機制」的具體參考文獻，本次未下載，若未來要讓 `citations_json` 的信心融合更精確（例如偵測同一來源網站/作者的重複轉載），可作為下一步查證方向。
- [ ] 尚未查證是否有開源專案完整實作「單一事實邊 + 累積來源清單」這個具體資料結構（Neo4j 邊屬性存 JSON 陣列），僅有 Wikidata（非 Neo4j、非本論文架構）與 KV（無結構化清單、僅信心分數）兩個文獻層級的功能性先例，實作層級的參考專案查證留待第四章。
