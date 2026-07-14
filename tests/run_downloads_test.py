import sys
import os
from pathlib import Path

# 將專案根目錄加入 path
sys.path.append(str(Path(__file__).parent.parent))

from parser.core import DocumentParser, sentence_aware_chunking

def test_file_parsing(parser: DocumentParser, file_path: str, label: str):
    print(f"\n==================================================")
    print(f"🔍 測試檔案類型: {label}")
    print(f"📂 檔案路徑: {file_path}")
    print(f"==================================================")
    
    if not os.path.exists(file_path):
        print(f"❌ 測試失敗: 找不到該檔案！請確認路徑。")
        return
        
    try:
        # 開始解析
        text = parser.parse_file(file_path)
        char_count = len(text)
        print(f"✅ 解析成功！總字元數: {char_count}")
        
        # 顯示前 500 字
        print("\n📝 --- 解析內容前 500 字預覽 ---")
        preview = text[:500]
        print(preview)
        print("--------------------------------")
        
        # 測試分塊
        chunks = sentence_aware_chunking(text, chunk_size=300, chunk_overlap=30)
        print(f"📦 句子感知分塊成功！生成 Chunk 數: {len(chunks)}")
        if chunks:
            print(f"   └─ 第一個 Chunk 預覽: {chunks[0][:150]}...")
            
    except Exception as e:
        print(f"❌ 解析過程中發生異常: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    parser = DocumentParser()
    downloads_dir = "d:/Users/666/Downloads"
    
    # 測試清單 (選擇 4 個不同類型的真實檔案)
    test_cases = [
        ("d:/Users/666/Downloads/FK簡介.docx", "Word DOCX 測試"),
        ("d:/Users/666/Downloads/在代理系統中的小語言模型：架構、功能與部署權衡的綜述.pdf", "中文 PDF 雙欄還原測試"),
        ("d:/Users/666/Downloads/06.20.DeepSeek-Reasoning Model.2.pdf", "英文學術論文 PDF 測試"),
        ("d:/Users/666/Downloads/KOI無人泡茶機簡報.pptx", "PowerPoint PPTX 測試")
    ]
    
    for path, label in test_cases:
        test_file_path = os.path.normpath(path)
        test_file_parsing(parser, test_file_path, label)
