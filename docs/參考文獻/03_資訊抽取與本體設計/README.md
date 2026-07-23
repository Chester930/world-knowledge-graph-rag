# 03_資訊抽取與本體設計

對應 `../../論文/02_文獻探討.md` § 2.4.4（對應 3.3，受控語意關係抽取，2026-07-23 第二章重組前為 § 2.1.3）。
本資料夾支撐 **RQ4（預留）**：以 Schema.org 為錨點的受控關係詞彙標準化。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `vashishth-et-al-2018-cesi-canonicalize-open-kb.pdf` | Vashishth, Jain & Talukdar (2018), *CESI: Canonicalizing Open Knowledge Bases using Embeddings and Side Information*, WWW 2018 | arXiv:1902.00172 | ✅ 已下載 |
| `angeli-et-al-2015-stanford-openie.pdf` | Angeli, Premkumar & Manning (2015), *Leveraging Linguistic Structure for Open Domain Information Extraction*, ACL 2015 | ACL Anthology P15-1034 | ✅ 已下載 |
| `guha-et-al-2016-schema-org-cacm.pdf` | Guha, Brickley & Macbeth (2016), *Schema.org: Evolution of Structured Data on the Web*, CACM Vol.59 No.2 | DOI: [10.1145/2844544](https://doi.org/10.1145/2844544) | ⚠️ **付費資源**，ACM 直接下載為登入頁面；2026-07-20 再次查證 ResearchGate／Academia.edu 皆非作者授權的免費全文（前者僅為「request full-text」頁面，後者需帳號且來源不明），確認目前無合法免費全文，仍需透過學校圖書館下載 |
| `vrandecic-krotzsch-2014-wikidata.pdf` | Vrandečić & Krötzsch (2014), *Wikidata: A Free Collaborative Knowledgebase*, **CACM 57(10), 78-85** | DOI: [10.1145/2629489](https://doi.org/10.1145/2629489)，作者授權開放取用全文：https://iccl.inf.tu-dresden.de/w/images/8/89/Wikidata-CACM-2014.pdf | ✅ 🟢 已下載並精讀全文（2026-07-20） |

## 各文獻與 RQ4 的對應關係

| 文獻 | 在 RQ4 中的角色 |
|---|---|
| **Guha et al. (2016) Schema.org** | Schema.org 的學術錨點——引用此文來說明「以公認 Web 標準作為詞彙錨點」是有文獻支撐的設計選擇，而非自創標準；**因全文尚未取得，本論文正文對其論證細節的引用仍受限，見下方 Vrandečić & Krötzsch 作為部分替代來源的說明** |
| **Vrandečić & Krötzsch (2014) Wikidata**（2026-07-20 新增，作為 Guha et al. 全文未取得前的可查證替代來源） | 精讀全文後確認：Wikidata 提供一個**已發表、開放取用、可獨立查證**的「社群治理受控詞彙擴展」真實案例——屬性（property）頁面本身**必須指定 datatype**（結構層限制，決定該屬性能接受哪種值），且**schema 本身與資料一樣受社群控制**（"Contributors edit the population number of Rome but also decide whether there is such a number in the first place"），社群另會為屬性訂定（軟性）語意限制條件（如「一個項目最多只能有一個出生地」）並用外部工具掃描違反此限制的資料。**誠實的適配度說明**：本文並未如本論文 3.3 節設計提案般，明確描述一套「結構驗證→語意驗證」**兩階段、循序**的新詞彙審核閘門（Wikidata 的 datatype 限制與語意限制檢查分屬不同機制、非循序閘門），因此**不能宣稱兩者機制等價**；但確實驗證了「受控詞彙的結構層與語意層可分別治理」這個大方向在生產級系統中是可行且已規模化運作（1,176 個屬性、4300 萬筆陳述句，2014 年數據）的設計模式，可作為 Schema.org 之外、獨立可查證的佐證來源 |
| **Vashishth et al. (2018) CESI** | 直接命名開放式 IE 產生語意相同但字面不同的關係（即「Semantic Drift」問題），並透過嵌入式叢集做規範化——說明本論文要解決的問題在學界已被正式識別 |
| **Angeli et al. (2015) Stanford OpenIE** | 開放式關係抽取的代表性基準線——RQ4 的對照組；說明開放式抽取為什麼是主流選擇，以及本論文封閉式設計刻意反其道而行的動機 |

## 待辦

- [ ] 若後續仍需 Guha et al. 全文細節（而非僅需「受控詞彙有生產級先例」這個較粗的論點），透過學校圖書館或機構帳號下載 `guha-et-al-2016-schema-org-cacm.pdf`（DOI: 10.1145/2844544）；Vrandečić & Krötzsch (2014) 已可支撐較粗粒度的論點，此項不再是 RQ4 的阻斷性待辦
- [ ] 精讀 CESI 論文方法論，確認「語意漂移」（Semantic Drift）問題的定義與本論文設計的對照關係
- [ ] 設計 RQ4 對照組實驗（開放式 vs 受控式）的評估方法論
- [ ] 確認 Schema.org 屬性的覆蓋率：在本系統語料中，30 種 SVO 關係有多少比例能直接映射到 schema: 屬性？
