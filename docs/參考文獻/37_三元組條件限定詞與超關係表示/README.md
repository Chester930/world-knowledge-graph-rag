# 37_三元組條件限定詞與超關係表示

對應 `../../論文/02_文獻探討.md` § 2.4.4／§ 2.6.2（3.1.3 SVO 抽取 prompt 規則7的副作用診斷）；`docs/報告/65_抽取粒度修復設計SDD任務書.md`（設計提案本身，**尚未實作，待使用者核准**，本資料夾僅記錄查證過程與結果）。

本資料夾不另存 PDF，僅 README 記角色＋WebSearch 即時查證（2026-09-22），比照 `32_法規結構感知切塊與主旨錨定/`、`36_法律領域RAG基準/` 的輕量作法。

## 起點：問題是什麼

報告57 §4.21／報告62 §4.21 的「20 題檢索失敗歸因複核」發現 35 個持續未命中的 gold span 中，14 個（40%）屬於「抽到但破碎／丟失限定條件」——本專案 `services/svo_service.py::_svo_prompt()` 規則7刻意要求「一句話的每一項附加規定都各自拆成獨立三元組」（報告18/19/20 時期為修「遺漏」問題而設計），副作用是遇到「共同條件 → 一個或多個結果」的複合法規句時，條件與結果被拆進互不相干的三元組，任一筆單獨拿出來都不完整（例如 `57-AGGR19` 丟了「依前項第一款規定」這個適用範圍限定，即使該 Fact 排名第1名仍判未命中）。查證目的：這個「原子分解 vs. 保留條件完整性」的取捨，學界是否已有對應做法。

## 查證結果（2026-09-22，WebSearch，即時查證，未逐字精讀全文）

### 1. Chen et al. (2023/2024) Dense X Retrieval — 既有引用，補充「去脈絡化」判準

本專案已在 `08_向量化與語意表示/`（`02_文獻探討.md` § 2.6.2）引用此文獻佐證「proposition 級細粒度檢索」，但先前引用僅用於「切塊粒度」這個論點。2026-09-22 重新查證其 proposition 定義發現，該文獻對「proposition」的判準明確包含**去脈絡化（decontextualization）**：

> "Decontextualize the proposition by adding necessary modifier to nouns or entire sentences and replacing pronouns... This ensures that necessary context from the passage is incorporated so that the meaning of the proposition can be interpreted independently of the original text."

**與 F 的對應**：F 方向A（在抽取 prompt 加規則，要求把共同條件複述進每一筆衍生三元組的 verb 裡）正是這個「去脈絡化」判準的一個具體實例——讓每個原子單元不需要依賴同句其他三元組就能被獨立理解。**誠實聲明**：原文的去脈絡化操作對象是代名詞指代與名詞修飾語，範例是段落層級的文本（如「這座塔」→「比薩斜塔」），不是法規條文「條件子句→多個並列結果」這種結構；本專案援引的是其**判準精神**（原子單元須自足可解讀），不是其具體演算法或應用場景，兩者論域不同。

### 2. Galkin, Trivedi, Maheshwari, Usbeck & Lehmann (2020) StarE — 超關係知識圖譜／qualifier

> **Message Passing for Hyper-Relational Knowledge Graphs**，EMNLP 2020，<https://arxiv.org/abs/2009.10847>

超關係知識圖譜（hyper-relational KG）在主要三元組之外，附掛任意數量的 key-value **qualifier**（如 Wikidata statement model），用來「消歧義或限制一則事實的有效範圍」（原文：qualifiers "disambiguate, or restrict the validity of a fact"）。這與 `57-AGGR19` 被丟掉的「依前項第一款規定」在語意角色上高度對應——那正是一個限制主要三元組（「職業災害勞工終止勧動契約時，準用勞動基準法規定預告雇主」）適用範圍的 qualifier，不是應該被拆成獨立三元組、也不是應該被丟棄的資訊。StarE 論文的實證結果（linked prediction 任務上比純三元組表示法提升最高 25 MRR points）佐證「qualifier 化保留範圍/條件資訊」對下游任務有實質效益，不只是表示法上的美觀。

**與 F 的對應**：這是比「方向A（條件複述進 verb 文字）」更**原則性**的第三個候選方向（方向C）——把限定條件建模為 Fact 節點的顯式 qualifier（例如新增 `Fact.scope_qualifier` 屬性或獨立的 `QUALIFIED_BY` 邊），而不是塞進自然語言 verb 字串裡讓下游 embedding／LLM 自行解讀。**誠實聲明**：StarE 是連結預測（link prediction）的表示學習模型，訓練目標與資料規模（Wikidata 等大型 KG）與本專案「LLM prompt 抽取＋cosine 檢索」的技術路線完全不同，**具體演算法不可直接套用**，僅能佐證「qualifier 是比拆散成獨立三元組更成熟的知識表示方式」這個大方向在學界有正式理論與實證基礎；採用此方向需要 Fact schema 變更＋既有 16826 筆 Fact 的 backfill，工程成本明顯高於方向A，本輪僅記錄為候選、不列入本階段實作範圍。

### 3. Krótkiewicz, Miasko & Jodłowiec (2026) — 法律規範顯式範圍表示

> **A Semantic Approach for Legal Norm Representation with Explicit Scope and Deontic Modality**，ACIIDS 2026（*Intelligent Information and Database Systems*, Lecture Notes in Computer Science vol. 16530, Springer）

⚠️ **誠實聲明（查證強度受限）**：僅透過 WebSearch 取得標題／作者／出版年份／期刊卷次與摘要層級描述（該文獻提出「一個明確捕捉規範範圍與義務模態，並將其作為一階語意構件」的語意 metamodel），**全文被 Springer 付費牆擋下，未能取得、未逐字精讀**，因此**只能引用其問題定義層級的主張**（法律規範的「範圍」（scope）值得被顯式建模、而非隱含在自然語言裡），**不能引用其具體技術機制**（不知道它是否也採用類似 qualifier 的做法，或是完全不同的形式邏輯路線）。列入本資料夾是為了佐證「F 想解決的問題（法規條件範圍在抽取/表示過程中流失）在法律資訊學界是 2026 年仍在研究的活躍問題，非本專案自行想像」，不作為技術方案的直接依據。

## 與 F 三個候選方向的對應關係

| 候選方向 | 文獻對應 | 佐證強度 |
|---|---|---|
| A（prompt 規則：條件複述進每筆衍生三元組的 verb） | Chen et al. (2023/2024) 去脈絡化判準 | 中——判準精神直接對應，但原文未處理法規條件子句這種結構，具體做法是本專案自行設計 |
| C（Fact schema 新增 qualifier／scope 欄位，不複述進 verb 文字） | Galkin et al. (2020) StarE、Wikidata statement model | 中高——超關係表示法是成熟研究方向且有量化實證效益，但論域（連結預測 vs. LLM 抽取+檢索）不同，具體演算法不可套用 |
| （問題本身是否重要，跨方向的背景佐證） | Krótkiewicz et al. (2026) | 弱——僅問題框架層級佐證，未讀全文，不構成技術依據 |
| B（Fact 補句子層級 provenance，檢索時撈同句兄弟 Fact） | 本次查證未找到直接對應文獻；OIE 領域慣例（如 OPIEC 語料庫——Gashteovski, Wanner, Hertling, Broscheit & Gemulla, 2019, *OPIEC: An Open Information Extraction Corpus*, AKBC 2019，<https://arxiv.org/abs/1904.12324>，每筆三元組附帶 provenance sentence 與依存句法解析）普遍會替每筆三元組保留來源句子/依存句法的 provenance，但那是「保留可追溯性」，不是「用 provenance 做檢索時的同句聚合補償」，兩者問題不同 | 弱——僅佐證「保留句子層級 provenance」本身是 OIE 領域常見做法（`SVOTriple.source_sentence_start/end` 本專案已有此欄位，但目前未寫入 Fact 節點本身，見報告65），聚合補償機制本身查無先例 |

## 誠實的文獻缺口

**沒有找到任何文獻直接研究「LLM prompt 抽取時，如何在『避免遺漏』與『避免拆散丟失條件完整性』兩個目標之間取捨」這個具體問題**——這正是報告61 一貫的誠實立場（「沒有文獻能證明具體做法有效」）在 F 這個子問題上的延伸。上述三篇/一項研究方向只能佐證「條件/範圍應被顯式保留」這個大原則在相鄰領域（proposition 檢索、超關係知識圖譜、法律語意表示）已被認真對待，**不能宣稱有文獻證明方向A或方向C對本專案的法規三元組抽取任務確實有效**——這仍須靠報告65 §（驗證計畫）的定向重抽實測來確認，不能只憑文獻類推就直接大規模採用。

## 待辦

- [ ] 若使用者核准方向A，定向重抽驗證後應回頭補記本資料夾「實測是否支持文獻類推」的結論（無論正反）。
- [ ] 若後續評估方向C（qualifier schema），需另行查證 Wikidata statement model 的官方文件（`vrandecic-krotzsch-2014-wikidata.pdf`，已存於 `03_資訊抽取與本體設計/`）是否有更具體、可套用的 qualifier 資料結構範例可參考，避免重新發明。
- [ ] Krótkiewicz et al. (2026) 全文若未來能取得（機構訂閱／作者自存版），應重新查證其技術機制是否比 qualifier 更貼近法規領域，並更新本表佐證強度。
