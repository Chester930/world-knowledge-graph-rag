import os
import shutil
import tempfile
import asyncio
from fastapi import FastAPI, UploadFile, File
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from parser.core import DocumentParser, URLParser

app = FastAPI(title="Ingestion Parser Debug Server")

# 掛載靜態檔案與樣板
app.mount("/static", StaticFiles(directory="ui/static"), name="static")
templates = Jinja2Templates(directory="ui/templates")

@app.get("/", response_class=HTMLResponse)
async def redirect_to_debug(request: Request):
    return templates.TemplateResponse(request, "parser_debug.html")

@app.get("/parser-debug", response_class=HTMLResponse)
async def parser_debug(request: Request):
    return templates.TemplateResponse(request, "parser_debug.html")

@app.post("/documents/debug-parse")
async def debug_parse_document(file: UploadFile = File(...)):
    """臨時上傳並解析文件，不依賴 Neo4j 或 LLM Providers，適合獨立測試轉譯器"""
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    try:
        parser = DocumentParser()
        loop = asyncio.get_running_loop()
        # 在執行緒池中跑 CPU-bound 的解析任務，防阻塞
        text = await loop.run_in_executor(None, parser.parse_file, temp_path)
        return {"filename": file.filename, "text": text}
    except Exception as e:
        return {"filename": file.filename, "text": f"解析失敗: {str(e)}\n\n請確認系統是否已安裝 Poppler 與 Tesseract-OCR，且已加入環境變數 PATH 中。"}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/documents/debug-parse-url")
async def debug_parse_url(payload: dict):
    """臨時下載並解析網頁或 YouTube 連結，不依賴 Neo4j，適合獨立測試"""
    url = payload.get("url")
    if not url:
        return {"filename": "Error", "text": "請提供 url 參數"}
    try:
        parser = URLParser()
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, parser.parse_url, url)
        return {"filename": url, "text": text}
    except Exception as e:
        return {"filename": url, "text": f"解析失敗: {str(e)}\n\n(若是 YouTube 字幕，請確認該影片是否有字幕；若是網頁，請確認 URL 是否有效。)"}


if __name__ == "__main__":
    import uvicorn
    print("\n🚀 [Ingestion Parser 獨立測試伺服器已啟動]")
    print("👉 請在瀏覽器開啟: http://127.0.0.1:8080/parser-debug\n")
    uvicorn.run("debug_server:app", host="127.0.0.1", port=8080, reload=True)

