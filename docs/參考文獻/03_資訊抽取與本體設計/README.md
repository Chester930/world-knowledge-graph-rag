# 03_資訊抽取與本體設計

對應 `../../論文/02_文獻探討.md` § 2.4.4（對應 3.1.3／3.1.4／3.2 §b／3.3，受控語意關係抽取與查詢時關係連結，2026-07-23 第二章重組前為 § 2.1.3）。
本資料夾支撐 **RQ4a（預留）**：受控關係詞彙的具體內容依據（實體類型／關係類型），以及查詢時「使用者措辭→canonical 類型」的關係連結機制。

> **2026-07-24 範疇擴充說明**：本資料夾原本只涵蓋「Schema.org 為錨點的受控關係詞彙標準化」這個較窄的主題；因應 3.1.3 節設計討論（實體類型改為選填/多值、關係類型收斂為扁平的 ConceptNet 36 類、新增查詢時關係連結機制），本次新增 6 篇文獻，分兩組：① 公用類型庫的具體內容依據（OntoNotes、ConceptNet）與其結構性佐證（ACE、Aguilar et al.）；② 查詢時關係連結（Relation Linking）機制依據（STAGG、Falcon 2.0、SLING）。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `vashishth-et-al-2018-cesi-canonicalize-open-kb.pdf` | Vashishth, Jain & Talukdar (2018), *CESI: Canonicalizing Open Knowledge Bases using Embeddings and Side Information*, WWW 2018 | arXiv:1902.00172 | ✅ 已下載 |
| `angeli-et-al-2015-stanford-openie.pdf` | Angeli, Premkumar & Manning (2015), *Leveraging Linguistic Structure for Open Domain Information Extraction*, ACL 2015 | ACL Anthology P15-1034 | ✅ 已下載 |
| `guha-et-al-2016-schema-org-cacm.pdf` | Guha, Brickley & Macbeth (2016), *Schema.org: Evolution of Structured Data on the Web*, CACM Vol.59 No.2 | DOI: [10.1145/2844544](https://doi.org/10.1145/2844544) | ⚠️ **付費資源**，ACM 直接下載為登入頁面；2026-07-20 再次查證 ResearchGate／Academia.edu 皆非作者授權的免費全文（前者僅為「request full-text」頁面，後者需帳號且來源不明），確認目前無合法免費全文，仍需透過學校圖書館下載 |
| `vrandecic-krotzsch-2014-wikidata.pdf` | Vrandečić & Krötzsch (2014), *Wikidata: A Free Collaborative Knowledgebase*, **CACM 57(10), 78-85** | DOI: [10.1145/2629489](https://doi.org/10.1145/2629489)，作者授權開放取用全文：https://iccl.inf.tu-dresden.de/w/images/8/89/Wikidata-CACM-2014.pdf | ✅ 🟢 已下載並精讀全文（2026-07-20） |
| `hovy-et-al-2006-ontonotes.pdf` | Hovy, Marcus, Palmer, Ramshaw & Weischedel (2006), *OntoNotes: The 90% Solution*, HLT-NAACL 2006 Companion Volume: Short Papers, pp.57-60 | ACL Anthology [N06-2015](https://aclanthology.org/N06-2015/) | ✅ 🟢 已下載（2026-07-24） |
| `speer-et-al-2017-conceptnet.pdf` | Speer, Chin & Havasi (2017), *ConceptNet 5.5: An Open Multilingual Graph of General Knowledge*, AAAI 2017 | arXiv:[1612.03975](https://arxiv.org/abs/1612.03975) | ✅ 🟢 已下載（2026-07-24） |
| `aguilar-et-al-2014-ace-ere-tackbp-framenet-comparison.pdf` | Aguilar, Beller, McNamee, Van Durme, Strassel, Song & Ellis (2014), *A Comparison of the Events and Relations Across ACE, ERE, TAC-KBP, and FrameNet Annotation Standards*, Proceedings of the 2nd Workshop on EVENTS (ACL 2014), pp.45-53 | ACL Anthology [W14-2907](https://aclanthology.org/W14-2907/) | ✅ 🟢 已下載（2026-07-24） |
| `yih-et-al-2015-staged-query-graph-generation.pdf` | Yih, Chang, He & Gao (2015), *Semantic Parsing via Staged Query Graph Generation: Question Answering with Knowledge Base*, ACL-IJCNLP 2015, pp.1321-1331 | ACL Anthology [P15-1128](https://aclanthology.org/P15-1128/)；官方程式碼 [scottyih/STAGG](https://github.com/scottyih/STAGG)（111★，2026-07-24 查證） | ✅ 🟢 已下載（2026-07-24） |
| `sakor-et-al-2020-falcon2.pdf` | Sakor, Singh, Patel & Vidal (2020), *Falcon 2.0: An Entity and Relation Linking Tool over Wikidata*, CIKM '20 | arXiv:[1912.11270](https://arxiv.org/abs/1912.11270)；官方程式碼 [SDM-TIB/falcon2.0](https://github.com/SDM-TIB/falcon2.0)（120★，2026-07-24 查證） | ✅ 🟢 已下載（2026-07-24） |
| `mihindukulasooriya-et-al-2020-sling-relation-linking.pdf` | Mihindukulasooriya et al. (2020), *Leveraging Semantic Parsing for Relation Linking over Knowledge Bases*, ISWC 2020 (LNCS 12506) | arXiv:[2009.07726](https://arxiv.org/abs/2009.07726)；程式碼收錄於 [IBM/neuro-symbolic-ai](https://github.com/IBM/neuro-symbolic-ai)（123★，2026-07-24 查證） | ✅ 🟢 已下載（2026-07-24） |

**未下載（標註規範非期刊論文，僅記書目）**：ACE 2005（Automatic Content Extraction）Relation Extraction Task 標註規範，Linguistic Data Consortium（LDC）發布——⚠️ 誠實聲明：這是 LDC 的任務標註規範文件（annotation guideline），性質上是標註標準/spec，不是同行評審出版品，不適用 🟢/🟡 信任分級；6 個粗類（`PART-WHOLE`／`PHYSICAL`／`PERSONAL-SOCIAL`／`ORG-AFFILIATION`／`AGENT-ARTIFACT`／`GEN-AFFILIATION`）、總計 18 個細類這個事實，透過上方 Aguilar et al. (2014) 這篇正式發表的比較論文查證存在性，未另外取得 LDC 原始標註規範全文。

## 各文獻與 RQ4a 的對應關係

| 文獻 | 在 RQ4a 中的角色 |
|---|---|
| **Guha et al. (2016) Schema.org** | Schema.org 的學術錨點——引用此文來說明「以公認 Web 標準作為詞彙錨點」是有文獻支撐的設計選擇，而非自創標準；**因全文尚未取得，本論文正文對其論證細節的引用仍受限，見下方 Vrandečić & Krötzsch 作為部分替代來源的說明** |
| **Vrandečić & Krötzsch (2014) Wikidata**（2026-07-20 新增，作為 Guha et al. 全文未取得前的可查證替代來源） | 精讀全文後確認：Wikidata 提供一個**已發表、開放取用、可獨立查證**的「社群治理受控詞彙擴展」真實案例——屬性（property）頁面本身**必須指定 datatype**（結構層限制，決定該屬性能接受哪種值），且**schema 本身與資料一樣受社群控制**（"Contributors edit the population number of Rome but also decide whether there is such a number in the first place"），社群另會為屬性訂定（軟性）語意限制條件（如「一個項目最多只能有一個出生地」）並用外部工具掃描違反此限制的資料。**誠實的適配度說明**：本文並未如本論文 3.3 節設計提案般，明確描述一套「結構驗證→語意驗證」**兩階段、循序**的新詞彙審核閘門（Wikidata 的 datatype 限制與語意限制檢查分屬不同機制、非循序閘門），因此**不能宣稱兩者機制等價**；但確實驗證了「受控詞彙的結構層與語意層可分別治理」這個大方向在生產級系統中是可行且已規模化運作（1,176 個屬性、4300 萬筆陳述句，2014 年數據）的設計模式，可作為 Schema.org 之外、獨立可查證的佐證來源。**2026-07-24 補充**：此文的 `rdf:type` 式建模精神（型別本身也是一種陳述/edge，而非特殊保留屬性）也是 3.1.4 節「實體型別改為獨立 Type 節點＋屬於邊」建模決策的直接依據，不需另找新文獻 |
| **Vashishth et al. (2018) CESI** | 直接命名開放式 IE 產生語意相同但字面不同的關係（即「Semantic Drift」問題），並透過嵌入式叢集做規範化——說明本論文要解決的問題在學界已被正式識別 |
| **Angeli et al. (2015) Stanford OpenIE** | 開放式關係抽取的代表性基準線——RQ4a 的對照組；說明開放式抽取為什麼是主流選擇，以及本論文封閉式設計刻意反其道而行的動機 |
| **Hovy et al. (2006) OntoNotes**（2026-07-24 新增） | 公用**實體類型庫**具體內容的文獻依據——18 類 NER 標籤（11 個具名實體類型＋7 個數值類型），是業界最廣泛採用的實體類型集合，直接支撐 3.1.3／3.1.4 節「公用實體類型庫」的實際內容 |
| **Speer et al. (2017) ConceptNet 5.5**（2026-07-24 新增） | 公用**關係庫**具體內容的文獻依據——36 個核心關係（7 個對稱＋29 個非對稱），與現有 `SVO_REL_TYPES` 大量重疊（`IsA`/`PartOf`/`Causes`/`UsedFor`/`HasProperty`/`CreatedBy`/`DefinedAs`/`InstanceOf`/`SimilarTo` 等），直接支撐 3.1.3 節「關係類型收斂為扁平 36 類」這個設計定案的具體內容 |
| **ACE 2005 relation schema ＋ Aguilar et al. (2014)**（2026-07-24 新增） | 佐證「關係分兩層（粗類→細類）」這種組織方式本身在學界是常見且合理的做法（ACE 6 粗類→18 細類；Aguilar et al. 進一步比較 ACE／ERE／TAC-KBP／FrameNet 四套關係本體）。⚠️ **誠實聲明**：ACE 的 6 個粗類名稱（人物/組織/地點關係）與本論文因果/功能/比較領域不合，**不能直接套用其具體類別名稱**，僅能佐證「兩層分類法」這個結構性設計選擇本身合理——這也是本論文最終決定**不採用**兩層架構、改採扁平 36 類的部分原因（詳見 3.1.3 節設計討論） |
| **Yih et al. (2015) STAGG**（2026-07-24 新增） | 查詢時「使用者動詞措辭→canonical 關係類型」比對機制的**核心文獻**——原文以神經網路模型將問題與 predicate 序列投影到同一向量空間、以相似度比對，與本論文 3.2 §b 設計的「query 動詞 embedding vs. 36 個 canonical 類型 embedding，算 cosine 相似度」機制精神一致，差別僅在本論文不需重新訓練模型、直接用現成 embedding provider 即可 |
| **Sakor et al. (2020) Falcon 2.0**（2026-07-24 新增） | 佐證「Relation Linking／關係連結」是 KBQA 領域被廣泛研究的既定任務，非本論文獨創的孤立問題。⚠️ **誠實聲明**：Falcon 2.0 本身是**規則式**（rule-based）系統，非 embedding 相似度比對，與本論文機制不同，僅能佐證任務重要性，不能當作 cosine 機制本身的直接依據 |
| **Mihindukulasooriya et al. (2020) SLING**（2026-07-24 新增） | 補充佐證——結合語意剖析（AMR）＋遠端監督＋語意相似度多訊號的混合式關係連結系統，比 Falcon 2.0 更接近本論文機制（含相似度訊號），但仍是混合式，非純 cosine，角色同樣是佐證任務領域的成熟度 |

## 待辦

- [ ] 若後續仍需 Guha et al. 全文細節（而非僅需「受控詞彙有生產級先例」這個較粗的論點），透過學校圖書館或機構帳號下載 `guha-et-al-2016-schema-org-cacm.pdf`（DOI: 10.1145/2844544）；Vrandečić & Krötzsch (2014) 已可支撐較粗粒度的論點，此項不再是 RQ4a 的阻斷性待辦
- [ ] 精讀 CESI 論文方法論，確認「語意漂移」（Semantic Drift）問題的定義與本論文設計的對照關係
- [ ] 設計 RQ4a 對照組實驗（開放式 vs 受控式）的評估方法論
- [ ] 確認 Schema.org 屬性的覆蓋率：在本系統語料中，公用實體類型庫（OntoNotes 18 類）有多少比例能直接映射到 schema: Type？（2026-07-24 更正：此問題原本問「30 種 SVO 關係」，但 Schema.org 的 property 是綁定特定 Type 的具體屬性，與本論文抽象語意關係領域不合，此覆蓋率查核應改問**實體類型**而非關係，見 3.1.3 節「公用類型庫是否需要 Schema.org 補充」討論）
- [ ] （2026-07-24 新增）STAGG／Falcon 2.0／SLING 三篇皆僅查證存在性與角色定位，尚未逐篇精讀方法章節細節，寫作定稿前需比照其餘核心對照文獻補齊
- [ ] （2026-07-24 新增）BYOKG-RAG（Mavromatis et al., 2025, AWS Labs，🟡 僅 arXiv，未確認正式發表）曾在查證過程中被提及為當代 LLM 時代的補充線索，但 PDF 摘錄未能確認其是否真的採用「cosine 先篩、不確定再交給 LLM 仲裁」的具體流程，本次未正式採用，若需要更貼近 LLM 時代的佐證可再評估是否精讀全文
