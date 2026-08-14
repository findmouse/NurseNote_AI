"""FastAPI エントリポイント"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import settings
from app.db.session import engine

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.app_name,
    description=(
        "看護記録・退院サマリー作成支援 API。\n\n"
        "**本システムは記録作成の支援ツールであり、記録内容の最終責任は看護師にあります。**"
    ),
    version="0.1.0-M1",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# 開発用。本番では nginx 経由の同一オリジンになるため CORS は不要。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health", tags=["system"], summary="ヘルスチェック")
async def health() -> dict:
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
