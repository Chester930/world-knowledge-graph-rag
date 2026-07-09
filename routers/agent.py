from __future__ import annotations
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from models.document import ChatRequest

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat")
async def chat(payload: ChatRequest):
    """SSE 串流問答。

    TODO(v2 架構重整)：雙層 RAG 流程（ConceptNode 路由 -> BFS 圖遍歷 ->
    圖譜驅動文件取回 -> 自我精煉迴圈 -> LLM 串流）待重新設計後實作。
    """

    async def _stream():
        payload_json = json.dumps({"message": "尚未實作，待架構重整完成後補上"})
        yield f"event: error\ndata: {payload_json}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
