# 03_資訊抽取與本體設計

對應 `../../論文/02_文獻探討.md` § 2.1.3（資訊抽取與本體設計）。
本資料夾支撐 **RQ4（預留）**：以 Schema.org 為錨點的受控關係詞彙標準化。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `vashishth-et-al-2018-cesi-canonicalize-open-kb.pdf` | Vashishth, Jain & Talukdar (2018), *CESI: Canonicalizing Open Knowledge Bases using Embeddings and Side Information*, WWW 2018 | arXiv:1902.00172 | ✅ 已下載 |
| `angeli-et-al-2015-stanford-openie.pdf` | Angeli, Premkumar & Manning (2015), *Leveraging Linguistic Structure for Open Domain Information Extraction*, ACL 2015 | ACL Anthology P15-1034 | ✅ 已下載 |
| `guha-et-al-2016-schema-org-cacm.pdf` | Guha, Brickley & Macbeth (2016), *Schema.org: Evolution of Structured Data on the Web*, CACM Vol.59 No.2 | DOI: [10.1145/2844544](https://doi.org/10.1145/2844544) | ⚠️ **付費資源**，ACM 直接下載為登入頁面，僅記書目未下載全文，請透過學校圖書館下載 |

## 各文獻與 RQ4 的對應關係

| 文獻 | 在 RQ4 中的角色 |
|---|---|
| **Guha et al. (2016) Schema.org** | Schema.org 的學術錨點——引用此文來說明「以公認 Web 標準作為詞彙錨點」是有文獻支撐的設計選擇，而非自創標準 |
| **Vashishth et al. (2018) CESI** | 直接命名開放式 IE 產生語意相同但字面不同的關係（即「Semantic Drift」問題），並透過嵌入式叢集做規範化——說明本論文要解決的問題在學界已被正式識別 |
| **Angeli et al. (2015) Stanford OpenIE** | 開放式關係抽取的代表性基準線——RQ4 的對照組；說明開放式抽取為什麼是主流選擇，以及本論文封閉式設計刻意反其道而行的動機 |

## 待辦

- [ ] 透過學校圖書館或機構帳號下載 `guha-et-al-2016-schema-org-cacm.pdf`（DOI: 10.1145/2844544）
- [ ] 精讀 CESI 論文方法論，確認「語意漂移」（Semantic Drift）問題的定義與本論文設計的對照關係
- [ ] 設計 RQ4 對照組實驗（開放式 vs 受控式）的評估方法論
- [ ] 確認 Schema.org 屬性的覆蓋率：在本系統語料中，30 種 SVO 關係有多少比例能直接映射到 schema: 屬性？
