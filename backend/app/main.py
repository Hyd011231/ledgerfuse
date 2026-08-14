import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routes import router

app = FastAPI(title="合账 LedgerFuse", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.on_event("startup")
def _startup():
    init_db()


# 生产模式：直接托管前端构建产物，只开一个端口即可用。
# 打包后 dist 被收进可执行文件目录（见 ledgerfuse.spec 的 datas）。
if getattr(sys, "frozen", False):
    _dist = Path(sys._MEIPASS) / "dist"
else:
    _dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
else:
    @app.get("/")
    def root():
        return {"app": "合账 LedgerFuse", "docs": "/docs",
                "hint": "前端未构建：cd frontend && npm run build，或开发模式 npm run dev"}
