export const narrations: string[] = [
  "先用文獻定位：三元組不是我自創的格式，三元組品質驗證也不是可有可無的加分項。",
  "OpenIE 證明 relation triples 是開放資訊抽取裡長期使用的基礎形式。",
  "Text2KGBench 證明 KG 生成需要 benchmark 與 metrics，不能只靠主觀判斷輸出看起來像不像。",
  "CORE-KG 指出 LLM 建圖常見 hallucination、重複節點與 noisy graph，這支撐來源追溯和去重的必要性。",
  "CoDe-KG 支撐句子級處理、sentence decomposition 和 coreference resolution 對關係抽取品質的影響。",
  "Robust GraphRAG 更直接指出，錯誤或不完整的 KG 會造成 GraphRAG 檢索漂移與幻覺。",
  "所以共同結論是：LLM 抽出的三元組必須先被檢查，才適合進入可信圖譜。因為錯邊不是停在圖上，它會被 GraphRAG 拿去繼續走圖。",
];
