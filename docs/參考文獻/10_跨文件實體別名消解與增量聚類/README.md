對應 `../../論文/03_系統設計與方法論.md` § 3.4 §a／§b（RQ4b，實體指代與別名消解）與 `docs/報告/09_實體別名登記與動態標準名提升機制設計報告.md`。

**查證背景（2026-07-21）**：09 報告原稿提出「動態標準名提升（PK 比試）」機制——依「長度與資訊量優先」「結構完整度優先」「平手保留既有 Key」三條規則，在串流處理句子時動態決定實體別名登記表的標準名 Key。經兩輪查證（見對話紀錄，未另立報告檔）確認：09 報告原引用的 spaCy EntityLinker／fastcoref／Microsoft GraphRAG Entity Dictionary／CORE-KG／Text2KGBench／CESI／Wikidata 共 7 項佐證，**沒有一項描述這個具體的三規則 PK 比試演算法**，其中 spaCy（精確字串比對連結靜態 KB）、Microsoft GraphRAG（title/type 完全相同才合併，交由 LLM 摘要描述）、CESI（頻率加權質心）、Wikidata（社群共識最常用名稱）四項是**明確採用不同方法**，不是單純查無資料。

本資料夾收錄的 3 篇文獻，是換一個查證方向後找到、且**架構層面**（跨文件、隨新文件持續擴增的別名聚類）真正對得上使用者目標的先例；但「標準名選取規則」本身，仍需與 `03_資訊抽取與本體設計/` 資料夾已有的 CESI／Wikidata 交叉引用才能成立（見下方「兩層佐證的分工」）。

## 內容清單

| 檔案 | 文獻 | 來源 |
|---|---|---|
| `rao-et-al-2010-streaming-cross-document-coref.pdf` | Rao, McNamee & Dredze (2010), *Streaming Cross Document Entity Coreference Resolution*, **COLING 2010: Posters**, pp. 1050-1058 | ACL Anthology [C10-2121](https://aclanthology.org/C10-2121/)，開放取用 |
| `ji-et-al-2011-tac-kbp-overview.pdf` | Ji, Grishman & Dang (2011), *Overview of the TAC2011 Knowledge Base Population Track*, **TAC 2011 Proceedings** | 開放取用：https://blender.cs.illinois.edu/paper/kbp2011.pdf |
| `saeedi-et-al-2020-incremental-multi-source-er.pdf` | Saeedi, Peukert & Rahm (2020), *Incremental Multi-source Entity Resolution for Knowledge Graph Completion*, **ESWC 2020**（LNCS vol. 12123, Springer），DOI: [10.1007/978-3-030-49461-2_23](https://doi.org/10.1007/978-3-030-49461-2_23) | 開放取用預印本：https://preprints.2020.eswc-conferences.org/121230352.pdf；亦見 PMC7250616 |

## 各文獻在 RQ4b 中的角色

- **Rao, McNamee & Dredze (2010)**：跨文件實體指代消解領域**串流式處理**的先驅論文——明確對照傳統離線做法（貪婪聚合式聚類，需 O(n²) 空間與時間）與串流場景（高流量文字持續進來，聚類需增量更新），架構動機與本論文「之後有其他文件提到同一實體時，別名圖譜要能持續擴增」完全一致。**誠實侷限**：PDF 內容加密，未能逐字確認其是否描述具體的「標準名選取/更新規則」，僅確認架構層面吻合；寫作定稿前需再精讀方法章節。
- **Ji, Grishman & Dang (2011)，TAC-KBP 2011 track overview**：官方、跨文件、隨語料持續擴增聚類機制的最高權威先例——TAC-KBP Entity Linking track 自 2011 年起要求系統對「連結不到既有知識庫」的提及建立新的 NIL 聚類，後續文件中提到同一實體的提及需持續併入該聚類（NIL clustering，以 B-Cubed+ F1 評估）。此機制與 09 報告「登記表隨處理進度累積，別名可能回指遠早於鄰近句子的實體」的設計精神一致，且是產業/學界公認的標準評測任務，非單一論文的自創方法。**誠實侷限**：其標準名規則簡單（case-insensitive 字串完全比對、或依標註者/系統設計決定「首次具名提及」），並非長度或頻率導向的動態比較演算法。
- **Saeedi, Peukert & Rahm (2020)**：**知識圖譜場景**下最貼近本論文目標的先例——處理「多來源資料持續加入知識圖譜時，既有實體聚類如何增量更新、且結果不依賴資料加入順序」，並提出輕量級聚類修復機制（整合於 FAMER 框架）。與 09 報告「跨文件別名圖譜隨時間持續擴增」的目標場景最為貼近（KG completion，非單純 NLP 指代消解）。**誠實侷限**：論文對「代表值（canonical value）」的選取只說明「合併成員屬性值」，未給出本論文需要的具體規則。

## 兩層佐證的分工（誠實框架，呼應 3.7 節）

09 報告的機制實際上分兩層，需分開標註佐證狀態，不可混為一談：

1. **跨文件增量聚類架構**（「新文件進來時別名圖譜如何擴增」）——本資料夾 3 篇提供真實文獻/benchmark 先例，可標註為「有文獻佐證的既有方向」。
2. **標準名選取規則**（「同一實體多個字面形式，哪一個當標準名」）——依 2026-07-21 使用者與 AI 討論定案，改採**出現頻率優先、長度僅作平手時的次要規則**，此規則的文獻依據**交叉引用 `../03_資訊抽取與本體設計/README.md`**：Wikidata（Vrandečić & Krötzsch, 2014）明確以「社群共識最常用名稱」選 label，CESI（Vashishth et al., 2018）以「頻率加權質心」選代表字串——兩者皆是頻率導向，與本論文最終定案的規則方向一致；**原三規則版本的「結構完整度優先」「平手保留既有 Key」兩條細則，改版後已不再是主規則的一部分，若 09 報告日後仍保留其文字，需同步修正，避免與 3.4 節正文不一致**。

## 已查證但確認不適用的來源（供追溯，避免重複查證）

以下為 09 報告原稿引用、經查證後確認**不支持三規則 PK 比試演算法本身**的來源，無 PDF 可下載（查證方式為直接讀取官方文件/原始碼）：

| 來源 | 查證結果 | 查證方式 |
|---|---|---|
| spaCy `EntityLinker` | CONTRADICTS——精確別名比對連結至預建靜態知識庫，非動態比較 | 官方文件 https://spacy.io/api/entitylinker |
| fastcoref | CANNOT_VERIFY——僅輸出 coreference clusters，未描述代表字串選取邏輯 | GitHub README，https://github.com/shon-otmazgin/fastcoref |
| Microsoft GraphRAG Entity Dictionary | CONTRADICTS——title/type 完全相同才合併，描述交由 LLM 摘要，title 本身不換 | 官方 pipeline 文件 https://microsoft.github.io/graphrag/index/default_dataflow/ |

## 待辦

- [ ] 精讀 Rao et al. (2010) 全文方法章節，確認是否有可用的標準名更新細節（目前僅確認架構層面吻合）
- [ ] 若後續要精確引用 NIL clustering 的評估方法（B-Cubed+ F1），需另外查證 TAC-KBP 官方 EDL guidelines 文件（如 `TAC_KBP_2015_EDL_Guidelines_V1.2.pdf`，https://tac.nist.gov），本資料夾目前僅收錄 2011 track overview
- [ ] 09 報告全文需依本 README「兩層佐證分工」的結論同步修正（見 `docs/報告/09_實體別名登記與動態標準名提升機制設計報告.md` 待改項目）
