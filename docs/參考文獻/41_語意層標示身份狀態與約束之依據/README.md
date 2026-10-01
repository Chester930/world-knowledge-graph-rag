# 41_語意層標示、身份、狀態與約束之依據（I1：文獻與規格；I2：參考專案見 `參考專案原始碼閱讀.md`）

對應 [`../../報告/203_下一階段任務規劃_優化依據文獻與參考專案蒐集.md`](../../報告/203_下一階段任務規劃_優化依據文獻與參考專案蒐集.md) 與 [`../../報告/Lumori簡報語意層對照與缺口檢查_v0.2.md`](../../報告/Lumori簡報語意層對照與缺口檢查_v0.2.md)（§1.4 使用者設計、§10 實測）。本資料夾不另存全文（皆為開放網頁／開放規格，僅記連結與引文），比照 `37_`、`40_` 的輕量作法。

> ⚠️ **總聲明（沿用報告61／`40_` 總聲明）**：以下來源多數只證明「這類問題存在」或「系統這樣設計」，**沒有任何一筆證明「照這樣做會讓本專案的檢索／回答準確率更高」**。本資料夾是**蒐集依據，不是證明要做**。

## 查證方法與強度（2026-10-01）
- **每一則引文**都以程式抓取該 URL 的**原始 HTML／PDF 文字**（去標籤、正規化空白後）做子字串比對，**FOUND 才寫入**；`WebFetch` 摘要頁因會改寫文字，**未作為引文來源**（曾發現其輸出與原文不符，已棄用）。
- 強度圖例：🟡＝一手頁面／規格／論文**片段**（讀了引用句所在的段落與其前後文，**未精讀全文**）；⚪＝僅搜尋結果摘要（**不得作為結論依據**，本資料夾若列出必標明）。**本次沒有任何一筆達「✅ 全文已讀」**。
- 既有登記（`01–40`）已涵蓋者只引編號：Zep／Graphiti 論文＝`02_RAG與GraphRAG/`、`40_`；Dense X、StarE、Wikidata statement model＝`37_`；實體去重開源專案＝`13_`。**本次未發現既有登記與一手來源不符之處**（只對 Zep 論文核對了 §2.2.3 一段，與 `40_` 的描述「矛盾時使舊邊失效而非刪除」一致）。

---

## G-A　缺值的語意：未知 vs 不適用

| 來源（URL；版本／日期） | 強度 | 逐字引文（英文） | 支持什麼 | 沒證明什麼 | 對應本專案發現 |
| --- | --- | --- | --- | --- | --- |
| Wikibase **Data Model**（<https://www.mediawiki.org/wiki/Wikibase/DataModel>；2026-10-01 取得） | 🟡（Snaks 一節） | "In some cases, we want to emphasize that a property value has not just been left out (or not entered yet) but that it really does not exist."／"This can be used if the value of a property is unknown."／"Stating this can be relevant to distinguish it from the (common) case that the property has simply not been entered into Wikidata yet." | **三種情形被明確區分**：*不存在*（`PropertyNoValueSnak`）、*未知*（`PropertySomeValueSnak`）、*尚未輸入*（文中描述為「常見情形」）。前兩者有專屬資料模型構件；〔推論〕第三者在模型中以「沒有該屬性的陳述」呈現（文中以「distinguish it from」描述，未稱其有專屬構件） | 論域是**人工編輯**的百科資料庫，非自動抽取；沒有量化實證；「尚未處理」在此是文字說明而非資料欄位值 | 實體型別佔位「概念」、`source_article_no` 的 `None`、空受詞（報告201 的三種標示） |
| Wikidata **Help:Statements**（<https://www.wikidata.org/wiki/Help:Statements>；2026-10-01） | 🟡（"Unknown or no values" 一節） | "There are times when for a given property an item has either no value (the absence of that property) or an unknown value."／"These data values may still provide important information about the item, and if so should be recorded in Wikidata." | 「無值」與「未知值」都是**要被記錄的正向資訊**，而不是留白 | 同上（人工編輯、無實證）；範例為單一屬性值（如無子女、出生日期未知），非三元組缺受詞 | 「不可靜默填補或丟棄」原則（v0.2 §1.4） |
| W3C **OWL 2 Syntax**（<https://www.w3.org/TR/owl2-syntax/>；W3C Recommendation 2012-12-11，Second Edition；2026-10-01） | 🟡 | "OWL 2 has open-world semantics, so negation in OWL 2 is the same as in classical (first-order) logic." | 本體語言預設**開放世界**：沒說的事不被當成假 | 只涉及邏輯語意，**不提供「標示缺值原因」的機制**；與抽取管線無直接關係 | 空欄位不應被當成「為假／不存在」 |
| PostgreSQL 文件 **Comparison Functions and Operators**（<https://www.postgresql.org/docs/current/functions-comparison.html>；current 版，2026-10-01） | 🟡 | "Ordinary comparison operators yield null"…"not true or false, when either input is null."（同節上下文：「(signifying “unknown”)」） | 資料庫的 NULL 被定義為**「未知」**（三值邏輯），不是「不存在」 | **SQL NULL 只有一種缺值，並未區分未知與不適用**（本欄為我對文件的讀解〔推論〕；文件未明說「不區分」）；未取得 Codd 原始論文 | `None` 同時代表不適用與可能的未知（報告201 §3） |

**G-A 結論**：**有直接依據支持「把缺值至少分成『不存在』與『未知』兩類並讓兩者在資料模型中可區分」**（Wikibase 資料模型，最直接）；三分法中的「尚未處理」在該來源只是文字描述、不是資料構件。〔把握度：中——來源可靠但為人工編輯系統，且是**設計描述而非效果實證**。〕**相反或不同的做法**：SQL 的單一 NULL（只代表未知）；OWL 的開放世界（不標示原因）。**查無**：針對「LLM 自動抽取結果」的缺值標示的實證研究（本次未找到）。

---

## G-B　身份：穩定識別碼與標籤分離、類型的剛性

| 來源 | 強度 | 逐字引文 | 支持什麼 | 沒證明什麼 | 對應本專案發現 |
| --- | --- | --- | --- | --- | --- |
| Wikidata **Help:Items**（<https://www.wikidata.org/wiki/Help:Items>；2026-10-01） | 🟡 | "Each item has a unique identifier (starting with a Q prefix)" | 實體以**識別碼**（Q 號）識別 | 無效果實證；人工編輯論域 | 唯一鍵為 `(kg_id,name)`（報告197） |
| Wikidata **Help:Label**（<https://www.wikidata.org/wiki/Help:Label>；2026-10-01） | 🟡 | "It does not need to be unique, in that multiple items can have the same label, however no two items may have both the same label and the same description" | **標籤可重複**（不同實體可同名），身份不靠名稱；以「標籤＋描述」才要求不重複 | 同上 | 標準名會被改寫（`svo_service.py:757-784`）；「身份＝可變名稱」 |
| **OntoUML／UFO** 文件 *Rigidity*（<https://ontouml.readthedocs.io/en/latest/theory/rigidity.html>；文件頁版權註記 2018，2026-10-01 取得） | 🟡 | "Examples of anti-rigid types are: Student, Employee, Spouse, Elder, Living Person and Healthy Person."／"Other examples of rigid types are: Person, Car, Band, Apple, Country and Company." | **Person 是剛性型別、Employee 是反剛性型別**——與簡報／使用者的「人 vs 員工身分、不同層級」直接同形；同頁列 `Role`／`Phase` 為反剛性構造 | 這是**概念建模理論的文件頁**，無實證；二手教學文件（非 Guizzardi 原始論文，**原始論文本次未取得**） | 使用者的「身分層級」；v0.2 §1.4 的 Person≠Employment |
| **schema.org `Role`**（<https://schema.org/Role>；2026-10-01） | 🟡 | "Represents additional information about a relationship or property."／"For example a Role can be used to say that a 'member' role linking some SportsTeam to a player occurred during a particular time period." | 標準詞彙**已有「關係帶屬性」的載體**（Role）；範例即「成員」關係帶**時間區間** | 內建屬性是 `startDate`／`endDate` 一類（頁面列有 `endDate`），**偏時間**；與使用者「不強制綁時間」不同（v0.2 §1.4 已有同樣觀察） | 使用者「名詞標準化用 schema.org」、關係帶內部屬性 |

**G-B 結論**：**有一手依據支持「識別碼與標籤分離」**（Wikidata 兩頁）與「類型剛性區分（Person vs Employee）」（OntoUML 文件）；但**皆為設計描述，無量化實證**，論域與本專案不同。〔把握度：中。〕**不同做法**：本專案以名稱為鍵、並依相似度合併（`40_`／`13_` 的去重文獻涵蓋「合併方法」，但**未涵蓋「識別碼與標籤分離」**，本次補上）。**查無**：「LLM 抽取知識圖譜中，識別碼與標籤分離能降低誤併」的實證。

---

## G-C　關係的時間與狀態：有效區間、失效、狀態機

| 來源 | 強度 | 逐字引文 | 支持什麼 | 沒證明什麼 | 對應本專案發現 |
| --- | --- | --- | --- | --- | --- |
| **Zep／Graphiti 論文**，Rasmussen et al.，arXiv:2501.13956 **v1**（2025-01-20）（<https://arxiv.org/html/2501.13956>；2026-10-01；已登記於 `02_`／`40_`，此處補讀 §2.2.3） | 🟡（§2.2.3 一段） | "The introduction of new edges can invalidate existing edges in the database."／"The system employs an LLM to compare new edges against semantically related existing edges to identify potential contradictions."／"These temporal data points are stored on edges alongside other fact information." | **失效而非覆寫**：新邊與舊邊矛盾時，舊邊被標示失效（保留歷史）；**失效的觸發是「LLM 偵測到矛盾」**（原文接著寫：偵測到「temporally overlapping contradictions」時才設定舊邊的 invalid 時間） | 論域是**對話式 agent 記憶**，非法規；效果是作者自報（摘要：DMR 94.8% vs 93.4%）；觸發雖是「矛盾」，**記錄與判定仍以時間點為核心**（`t_valid`／`t_invalid`） | 事實／邊無時間、無法表示「結束後重新開始」（報告197） |
| **Wikidata 時間 qualifier**：**Help:Qualifiers**（<https://www.wikidata.org/wiki/Help:Qualifiers>）與 **Property:P1534（end cause）**（<https://www.wikidata.org/wiki/Property:P1534>；2026-10-01） | 🟡 | P1534 說明："qualifier used together with the end date qualifier (P582) to specify the reason for the end"（Help:Qualifiers 以 `start time (P580)`／`end time (P582)` 為範例） | **起訖時間是陳述的 qualifier；結束的「原因」另有專屬 qualifier**——即**條件／事件原因被記錄，但與結束日期「一起使用」**（說明文字） | 原因 qualifier 是**附屬於結束日期**的；**不是以事件取代時間**；人工編輯 | 使用者「起訖由狀態轉換定義」 |
| Wikidata **Help:Ranking**（<https://www.wikidata.org/wiki/Help:Ranking>；2026-10-01） | 🟡 | "The deprecated rank is used for statements that are known to include errors"…"or that represent outdated knowledge"（同頁：預設為 normal rank，可標 preferred／deprecated） | **「失效」可以不經時間而以「等級」表示**（錯誤或過時的陳述被標為 deprecated 而不刪除） | 這是**同一屬性多值的優先順序機制**，不是關係生命週期；人工編輯 | 「更新不覆寫」 |
| W3C **OWL-Time**（<https://www.w3.org/TR/owl-time/>；**Candidate Recommendation Draft 2022-11-15**，非正式 Recommendation；2026-10-01） | 🟡 | "OWL-Time is an OWL-2 DL ontology of temporal concepts, for describing the temporal properties of resources in the world or described in Web pages." | 提供**時間詞彙**（instant／interval／時間位置） | **只是時間詞彙**，不含狀態機、失效或事件觸發的語意 | 若採時間屬性，可借用其詞彙（不等於支持使用者設計） |
| 狀態機式關係建模 | ⚪ | （無） | — | — | — |

**G-C 結論（特別回答「只以時間觸發，還是也支援條件／事件觸發」）**：
1. 本次查到的來源中，**所有「關係有效性」的機制，其記錄形態都是時間點或時間區間**（Zep 的 `valid`／`invalid`、Wikidata 的 start／end time、OWL-Time）。
2. **但「觸發失效」並非只靠時間**：Zep 以**偵測到與既有事實矛盾**（新資訊事件）觸發；Wikidata 另有**「end cause」qualifier**記錄結束原因，以及 deprecated rank 表示錯誤／過時而不經時間。故**文獻／專案「有」事件或條件層面的觸發與紀錄，但都是附掛在時間記錄之上**。
3. **查無**：把「**每個關係建成顯式狀態機（狀態、轉換、允許轉換、互斥狀態），且起訖由狀態轉換定義、不強制綁時間**」的知識圖譜文獻或系統。搜尋只找到通用的 UML／有限狀態機說明（⚪，二手，**不作依據**）；一手的 UML 規格（OMG）**本次未取得**。
4. **與使用者設計的差異**：使用者的設計（關係＝狀態機、時間只是轉換的可選依據）**在本次查證範圍內沒有直接對應的既有做法**；最接近的是「時間＋觸發原因」模式。**不評對錯，只列事實。** 〔把握度：中（查證範圍有限：未讀 temporal KG 文獻全文；`40_` 已登記的 temporal 文獻本次未重讀）。〕

---

## G-D　候選→已接納、信心與來源

| 來源 | 強度 | 逐字引文 | 支持什麼 | 沒證明什麼 | 對應本專案發現 |
| --- | --- | --- | --- | --- | --- |
| **NELL**，Mitchell et al.，*Never-Ending Learning*，AAAI 2015（<https://www.cs.cmu.edu/~tom/pubs/NELL_aaai15.pdf>；2026-10-01；9 頁 PDF） | 🟡（架構與 KI 段落） | "The Knowledge Integrator (KI) integrates the incoming proposals for KB updates."／"NELL constructs and considers only the beliefs in which it has highest confidence, limiting each software module to suggest only a bounded number of new candidate beliefs"／"the categories that are known to be disjoint from (mutually exclusive with) C are specified" | 系統**把各模組的提案當「候選信念（candidate beliefs）」，由整合器依信心與約束決定是否納入 KB**；並以**互斥、引數型別**等約束把關（"Coupling relations to their argument types."） | 本次讀到的段落**未出現具體的升格門檻數值**（搜尋摘要提到 0.9，屬 ⚪，**不引用**）；論域是開放網頁、非法規 | 抽出即 MERGE（報告197）；`confidence` 無語意 |
| **Knowledge Vault**，Dong et al.，KDD 2014（<https://research.google.com/pubs/archive/45634.pdf>；10 頁 PDF；2026-10-01） | 🟡 | "features a probabilistic inference system that computes calibrated probabilities of fact correctness"／"The confidence scores from each extractor (and/or the fused system) are not necessarily on the same scale, and cannot necessarily be interpreted as probabilities." | 抽取信心**需要校準才能當機率用**；系統對每個事實輸出**校準後的正確機率** | 作者自報；Google 規模、非法規；**未證明校準能提升下游問答** | `confidence` 是 1–5 整數、取最大值、未定義語意（報告197） |
| Wikidata **Help:Ranking**（同 G-C） | 🟡 | "The default rank is the"…（預設 normal；可標 preferred／deprecated） | 陳述有**等級**，可同時保存多個值並標示優先／棄用 | 非「候選→已接納」的流程，僅是同屬性多值的標示 | 候選／已接納的缺口 |
| W3C **PROV-O**（<https://www.w3.org/TR/prov-o/>；W3C Recommendation **2013-04-30**；2026-10-01） | 🟡 | "can use and generate a variety of Entities"（Activity 與 Entity 的關係；同節列 `prov:wasGeneratedBy`、`prov:wasAttributedTo`、`prov:startedAtTime`、`prov:endedAtTime`） | **標準的「來源／產生者／時間」詞彙**（Activity、Agent、wasGeneratedBy、wasAttributedTo、startedAtTime） | 只是**詞彙**，不規定抽取系統要記錄什麼；無實證 | 引用沒有抽取時間／模型／提示詞版本（報告197） |

**G-D 結論**：**有一手依據支持「候選與已採信分開、由整合步驟依信心與約束決定」（NELL）、「信心需校準」（Knowledge Vault）、「來源／產生者／時間有標準詞彙」（PROV-O）**。〔把握度：中。〕**皆是設計或作者自報，非本專案論域的效果實證。**相反／不同做法：本專案現行「抽出即寫入、`confidence` 取最大值」；LightRAG／GraphRAG 等實務專案也多是直接寫入（見 `參考專案原始碼閱讀.md`）。**查無**：RDF-star／屬性圖 statement 層級 metadata 的一手規格本次**未蒐集**（待查）。

---

## G-E　圖上的完整性約束

| 來源 | 強度 | 逐字引文 | 支持什麼 | 沒證明什麼 | 對應本專案發現 |
| --- | --- | --- | --- | --- | --- |
| W3C **SHACL**（<https://www.w3.org/TR/shacl/>；W3C Recommendation **2017-07-20**；2026-10-01） | 🟡（Abstract） | "This document defines the SHACL Shapes Constraint Language, a language for validating RDF graphs against a set of conditions." | 有**標準語言**用「形狀」宣告條件並驗證圖 | 針對 **RDF** 圖；本專案是 Neo4j 屬性圖；無實證 | 簡報第 6 步、報告196 的不變量清單 |
| **PG-Schema**，Angles et al.，arXiv:2211.10962（v4，2023-07-08）（<https://arxiv.org/abs/2211.10962>；2026-10-01） | 🟡（摘要） | "schema support is limited both in existing systems and in the first version of the GQL Standard."／"we propose PG-Schema, a simple yet powerful formalism for specifying property graph schemas." | 屬性圖**確實缺乏足夠的模式／約束支援**，並有提案的形式化語言 | 是**提案**，摘要未稱已被主流系統採用 | 本專案圖僅一條唯一約束 |
| Neo4j **Cypher Manual: Constraints**（<https://neo4j.com/docs/cypher-manual/current/schema/constraints/>；current，2026-10-01） | 🟡 | "It is, therefore, recommended to define a schema using a graph type, which offers both additional, more sophisticated constraint types" | 本專案所用資料庫的**官方文件已建議以 graph type 定義更豐富的約束**（頁面同時說明舊式 `CREATE CONSTRAINT` 語法） | 版本差異：本專案 Neo4j 版本是否支援 graph type **未核實**；無實證 | 不變量可否改為圖上約束（報告196 G6） |

**G-E 結論**：**有一手依據支持「圖可以用宣告式約束語言驗證」（SHACL）、「屬性圖的約束支援是已知缺口並有提案」（PG-Schema）、「Neo4j 官方文件有進階約束機制」**。〔把握度：中。〕**沒有任何來源證明「加約束能提升抽取品質」**；SHACL 對 RDF、本專案是屬性圖，須另評轉換成本。**查無**：ShEx 一手規格本次未蒐集（待查）。

---

## 本資料夾的限制與待查
- 全部為 🟡（片段），**無「全文已讀」**；W3C 規格只讀了引用句所在段落。
- 待查（未取得一手來源，**不得寫入結論**）：Codd 對缺失資訊的原始論文；Guizzardi 的 UFO／OntoUML 原始論文；RDF-star 規格；ShEx；OMG UML 狀態機規格；`40_` 已登記的 temporal KG 文獻本次未重讀。
- 若發現 `01–40` 既有登記與上列一手來源不符，請回報規劃對話（本次未發現）。
