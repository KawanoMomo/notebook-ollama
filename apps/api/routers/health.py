from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    ctx = request.app.state.ctx
    ok = True
    try:
        ctx.conn.execute("SELECT 1").fetchone()
        sqlite_ok = True
    except Exception:
        sqlite_ok = False
        ok = False
    return {
        "status": "ok" if ok else "degraded",
        "sqlite": sqlite_ok,
        "endpoint": ctx.config.ollama.endpoint,
        "version": "0.1.0",
    }
