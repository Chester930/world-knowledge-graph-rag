"""FastAPI 應用進入點（v2 骨架 — 待實作）。"""

from fastapi import FastAPI

app = FastAPI(title="智慧知識庫 v2")


@app.get("/health")
async def health():
    return {"status": "ok"}
