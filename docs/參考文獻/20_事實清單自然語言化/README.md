# 20_事實清單自然語言化

對應 `docs/報告/23_生成端事實清單排序機制優化設計報告.md` § 6.4、§7；`docs/論文/02_文獻探討.md` § 2.4.7；`docs/論文/03_系統設計與方法論.md` § 3.6。

## 起點

報告23 §6.4 的乾淨對照實驗確認：`routers/agent.py::_merge_fact_lines()` 目前把三元組格式化為 prompt 文字的樣板（`f"- {subject}（{subject_type}）{verb}{object}（{object_type}）"`）本身才是報告22題3失效案例的真正瓶頸——只把目標事實從這種生硬格式改寫成自然語句，位置完全不變，LLM 立刻引用了。位置工程（排序、截斷、zigzag重排，見文獻19）已到極限，需要另一條技術線：把結構化三元組轉換成更自然的文字表達，此即「triple verbalization」／「KG-to-Text」，NLP 領域內已有相當長的研究歷史。

## 內容清單

| 檔案 | 文獻 | 來源 | 狀態 |
|---|---|---|---|
| `gardent-et-al-2017-webnlg.pdf` | Gardent, Shimorina, Narayan & Perez-Beltrachini (2017), *The WebNLG Challenge: Generating Text from RDF Data* | INLG 2017（[ACL Anthology W17-3518](https://aclanthology.org/W17-3518/)） | ✅ 🟢 已下載（2026-09-01） |
| `wu-et-al-2023-retrieve-rewrite-answer.pdf` | Wu, Hu, Bi, Qi, Ren, Xie & Song (2023), *Retrieve-Rewrite-Answer: A KG-to-Text Enhanced LLMs Framework for Knowledge Graph Question Answering* | IJCKG 2023（[arXiv 2309.11206](https://arxiv.org/abs/2309.11206)） | ✅ 🟢 已下載並精讀摘要（2026-09-01） |

## 核心發現

**Gardent et al. (2017)**：WebNLG Challenge 是「把一組RDF三元組轉換成自然語言文字」（triple-to-text / data-to-text generation）這個研究任務的奠基性基準與命名論文——正式把這個問題定義為獨立的NLG子任務（涉及指稱表達生成、聚合、詞彙選擇、表層實現等一整套「microplanning」子問題），確立了這不是一個可以隨意樣板拼接就能解決的簡單問題，而是有專門研究脈絡的既定任務。屬2017年前LLM時代的傳統NLG技術基準，本專案不直接套用其pipeline架構，僅引用其**任務定義與問題命名**的權威性。

**Wu et al. (2023, IJCKG)**——與本專案今天的發現**幾乎逐字對應**。論文摘要明確指出：「Existing work...lack a well-formed verbalization of KG knowledge, i.e., they **ignore the gap between KG representations and textual representations**」——這正是報告23 §6.4驗證出的根因。論文提出「answer-sensitive KG-to-Text」方法：用fine-tuned LLM把選定的KG關係路徑轉換成「well-textualized statements」，取代直接把三元組拼接成文字（"triples verbalized by concatenating the subject, relation, and object"——**這正是本專案`_merge_fact_lines()`目前的做法**，論文稱其為基準/對照組）。**量化結果**：KG-to-Text改寫後的版本比直接拼接的triple-form text提升**1-8%**的QA準確率，比其他KG-to-Text模型也有1-5%提升——這是「三元組格式化文字本身會顯著傷害LLM引用/理解能力」的獨立量化實證，與本專案 §6.4 的定性對照實驗（同一事實、同一位置，只改措辭就從0次成功變1次成功）方向完全一致，互相佐證。

**參考專案查證（2026-09-01）**：Wu et al. 論文作者釋出官方程式碼（[wuyike2000/Retrieve-Rewrite-Answer](https://github.com/wuyike2000/Retrieve-Rewrite-Answer)，63★，2026-09-01 GitHub API 查證），可供對照KG-to-Text改寫模組的具體實作方式。**誠實侷限**：該repo的KG-to-Text模組需要**訓練/微調**一個獨立的seq2seq模型（fine-tuned LLM），是重量級的方案，不能直接套用本專案現有基礎設施——本專案若採用類似方向，應評估用既有 `LLMProvider`（Ollama／OpenAI等）做零樣本（zero-shot）改寫，而非重新訓練模型，這是報告23 §7候選方案(b)「查詢時LLM一次性改寫」的直接依據，但成本與精確度的權衡需另外評估，非直接複製此repo的訓練式做法。

**Microsoft GraphRAG 官方索引階段自然語言化先例（2026-09-01 新增查證）**：本專案已於 `docs/參考文獻/02_RAG與GraphRAG` 引用 Edge et al. (2024) GraphRAG 論文；[microsoft/graphrag](https://github.com/microsoft/graphrag) 官方倉庫（35,774★，2026-09-01 GitHub API 查證）的 `packages/graphrag/graphrag/prompts/index/community_report.py`（`COMMUNITY_REPORT_PROMPT`）是report23 §7候選方案(c)「抽取／索引階段預存自然語句版本」的官方實作先例——GraphRAG 在**索引建置階段**（非查詢時）用LLM把一個社群（community）內的結構化實體/關係 CSV 資料（`human_readable_id,title,description` 這類扁平表格）改寫成一份包含 TITLE／SUMMARY／DETAILED FINDINGS 的自然語言報告，查詢時直接檢索這份已經自然語言化的報告，而非每次查詢都重新組裝原始三元組。這與 Wu et al. 的**查詢時**改寫（方案b）形成互補的兩種時機選擇，皆屬KG-to-Text這條研究/工程脈絡，非孤立的個別做法。**誠實侷限**：GraphRAG 的社群報告是「整個社群」層級的摘要（多個實體/關係聚合成一份敘事報告），粒度比本專案「單一問答需要哪幾筆事實」粗得多，不能直接套用其pipeline，只能佐證「索引階段預先自然語言化」這個時機選擇本身是被驗證過的可行架構。

## 待辦

- [ ] 依報告23 §7候選方案(a)(b)(c)，評估三個方向的成本與可行性，確認優先實作順序，過程中應引用本資料夾文獻作為各方案的依據與邊界條件參照。
